import pandas as pd
import numpy as np
import re
from datetime import timedelta
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler
# from sklearn.model_selection import train_test_split # Not strictly needed for prediction part
import matplotlib.pyplot as plt
from torch.utils.data import TensorDataset, DataLoader
import os

# --- Configuration ---
# Determine the directory of the current script
script_dir = os.path.dirname(__file__)
# Build the absolute path to the data file relative to the script directory
DATA_PATH = os.path.join(script_dir, 'data/Time.csv')
# Number of future days to predict
PREDICT_DAYS = 30
# Sequence length for LSTM
SEQUENCE_LENGTH = 30  # Use last 30 days to predict the next day

# --- Data Loading and Preprocessing ---


def parse_sleep_time(time_str):
    """Converts sleep duration string 'X小时Y分' to total hours."""
    if pd.isna(time_str) or time_str == '':
        return np.nan
    hours = 0
    minutes = 0
    hour_match = re.search(r'(\\d+)\\s*小时', str(time_str))
    minute_match = re.search(r'(\\d+)\\s*分', str(time_str))
    if hour_match:
        hours = int(hour_match.group(1))
    if minute_match:
        minutes = int(minute_match.group(1))
    return hours + minutes / 60.0


def load_and_preprocess_data(file_path):
    """Loads and preprocesses the health data from CSV."""
    try:
        # Use the absolute path constructed earlier
        df = pd.read_csv(file_path, encoding='utf-8')  # Try UTF-8 first
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(file_path, encoding='gbk')  # Fallback to GBK
        except Exception as e:
            print(f"Error reading CSV with multiple encodings: {e}")
            return None
    except FileNotFoundError:
        print(f"Error: Data file not found at {file_path}")
        return None

    print("Original columns:", df.columns.tolist())

    # Rename columns for easier access (remove potential newlines)
    df.columns = [col.replace('\\r\\n', '').replace('\\n', '') for col in df.columns]
    print("Cleaned columns:", df.columns.tolist())

    # Select and rename relevant columns
    relevant_cols = {
        '日期': 'Date',
        '睡眠时间': 'SleepDuration',
        '体重': 'Weight',
        '体脂率': 'BodyFatPercentage',
        # Keep notes columns if needed for context, even if not predicted
        '健康情况': 'HealthNotes',
        '生活（饮食+社交+运动）': 'LifeNotes'
    }

    # Filter columns that actually exist in the dataframe
    existing_cols = {k: v for k, v in relevant_cols.items() if k in df.columns}
    if not existing_cols:
        print("Error: None of the expected columns (日期, 睡眠时间, etc.) were found in the CSV.")
        return None

    df = df[list(existing_cols.keys())]
    df = df.rename(columns=existing_cols)

    # Convert Date
    if 'Date' not in df.columns:
        print("Error: '日期' (Date) column is missing.")
        return None
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df = df.dropna(subset=['Date'])
    # Ensure sorting happens before finding last valid index
    df = df.sort_values('Date').reset_index(drop=True)

    # Convert Sleep Duration
    if 'SleepDuration' in df.columns:
        df['SleepDuration'] = df['SleepDuration'].apply(parse_sleep_time)

    # Convert Weight and Body Fat Percentage
    if 'Weight' in df.columns:
        df['Weight'] = pd.to_numeric(df['Weight'], errors='coerce')
    if 'BodyFatPercentage' in df.columns:
        # Remove '%' if present
        if df['BodyFatPercentage'].dtype == 'object':
            df['BodyFatPercentage'] = df['BodyFatPercentage'].str.replace('%', '', regex=False)
        df['BodyFatPercentage'] = pd.to_numeric(df['BodyFatPercentage'], errors='coerce')

    # Fill missing numerical data using forward fill then backward fill
    numeric_cols = ['SleepDuration', 'Weight', 'BodyFatPercentage']
    for col in numeric_cols:
        if col in df.columns:
            # Check if column exists AND has at least one non-NA value before filling
            if df[col].notna().any():
                df[col] = df[col].fillna(method='ffill').fillna(method='bfill')
            else:
                print(f"Warning: Column '{col}' is entirely empty or NaN. Cannot fill missing values.")

    # Fill missing text data with empty string (might not be needed for predictor, but keep for consistency)
    text_cols = ['HealthNotes', 'LifeNotes']
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna('')

    print("\\nProcessed Data Head:")
    print(df.head())
    print("\\nData Info:")
    df.info()
    print("\\nMissing values after processing:")
    print(df.isnull().sum())

    return df

# --- LSTM Model Definition ---


class LSTMPredictor(nn.Module):
    def __init__(self, input_size=1, hidden_layer_size=50, output_size=1):
        super().__init__()
        self.hidden_layer_size = hidden_layer_size
        self.lstm = nn.LSTM(input_size, hidden_layer_size, batch_first=True)
        self.linear = nn.Linear(hidden_layer_size, output_size)

    def forward(self, input_seq):
        batch_size = input_seq.size(0)
        h0 = torch.zeros(1, batch_size, self.hidden_layer_size).to(input_seq.device)
        c0 = torch.zeros(1, batch_size, self.hidden_layer_size).to(input_seq.device)
        lstm_out, _ = self.lstm(input_seq, (h0, c0))
        last_time_step_out = lstm_out[:, -1, :]
        predictions = self.linear(last_time_step_out)
        return predictions

# --- Time Series Prediction Function ---


def create_sequences(input_data, seq_length):
    """Creates sequences and labels for LSTM training."""
    sequences = []
    labels = []
    L = len(input_data)
    for i in range(L - seq_length):
        train_seq = input_data[i:i + seq_length]
        train_label = input_data[i + seq_length:i + seq_length + 1]
        sequences.append(train_seq)
        labels.append(train_label)
    if not sequences:  # Check if lists are empty before stacking
        return None, None
    return torch.stack(sequences), torch.stack(labels)


def predict_future(df, column_name, predict_days=PREDICT_DAYS, seq_length=SEQUENCE_LENGTH):
    """Trains an LSTM model and predicts future values for a given column."""
    if column_name not in df.columns or df[column_name].isnull().all():
        print(f"Column '{column_name}' not found or is all NaN. Skipping prediction.")
        return None, None

    print(f"\\n--- Predicting Future {column_name} ---")
    # Find the last valid index for the column *after* sorting by date
    last_valid_index = df[column_name].last_valid_index()
    if last_valid_index is None:
        print(f"Column '{column_name}' contains no valid data. Skipping prediction.")
        return None, None
    last_date = df.loc[last_valid_index, 'Date']
    print(f"Last date with actual data for {column_name}: {last_date}")

    # Use data up to the last valid point for training/prediction
    data_series = df.loc[:last_valid_index, column_name]
    data = data_series.dropna().values.astype(float)

    if len(data) < seq_length + 1:
        print(f"Not enough data points ({len(data)}) for {column_name} up to {last_date} to create sequences with length {seq_length}. Skipping.")
        return None, None

    # Normalize data
    scaler = MinMaxScaler(feature_range=(-1, 1))
    data_normalized = scaler.fit_transform(data.reshape(-1, 1))
    data_normalized = torch.FloatTensor(data_normalized)

    # Create sequences
    sequences, labels = create_sequences(data_normalized, seq_length)
    if sequences is None or len(sequences) == 0:
        print(f"Not enough data to create sequences for {column_name} with length {seq_length}.")
        return None, None

    # Model, Loss, Optimizer
    model = LSTMPredictor(input_size=1, output_size=1)
    loss_function = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    epochs = 150
    batch_size = 16

    # DataLoader
    dataset = TensorDataset(sequences, labels)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # Training Loop
    print(f"Training LSTM for {column_name}...")
    model.train()
    for i in range(epochs):
        epoch_loss = 0.0
        num_batches = 0
        for seq_batch, labels_batch in dataloader:
            optimizer.zero_grad()
            y_pred = model(seq_batch)
            labels_batch_reshaped = labels_batch.squeeze(1)
            single_loss = loss_function(y_pred, labels_batch_reshaped)
            single_loss.backward()
            optimizer.step()
            epoch_loss += single_loss.item()
            num_batches += 1
        avg_epoch_loss = epoch_loss / max(1, num_batches)  # Avoid division by zero
        if (i + 1) % 25 == 0:
            print(f'Epoch {i + 1}/{epochs} Average Loss: {avg_epoch_loss:.6f}')

    # Future Prediction Loop
    print(f"Generating future predictions for {column_name}...")
    model.eval()
    future_predictions_normalized = []
    current_sequence_normalized = data_normalized[-seq_length:].view(1, seq_length, 1)
    print(f"Last sequence input shape: {current_sequence_normalized.shape}")
    print(f"Last sequence input (first 5 values normalized): {current_sequence_normalized[0, :5, 0].tolist()}")

    for i in range(predict_days):
        with torch.no_grad():
            next_pred_normalized = model(current_sequence_normalized)
            future_predictions_normalized.append(next_pred_normalized.item())
            if i < 5:
                print(f"Normalized prediction {i + 1}: {next_pred_normalized.item()}")
            next_pred_tensor = next_pred_normalized.view(1, 1, 1)
            new_sequence_tensor = torch.cat((current_sequence_normalized[:, 1:, :], next_pred_tensor), dim=1)
            current_sequence_normalized = new_sequence_tensor

    # Inverse transform predictions
    future_predictions = scaler.inverse_transform(np.array(future_predictions_normalized).reshape(-1, 1))
    print(f"First 5 raw predicted values: {future_predictions.flatten()[:5]}")

    # Create future dates
    print(f"Last date in historical data (used for prediction start): {last_date}")
    future_dates = pd.date_range(start=last_date + timedelta(days=1), periods=predict_days)
    print(f"First 5 predicted dates: {future_dates[:5].tolist()}")

    predictions_df = pd.DataFrame({'Date': future_dates, f'{column_name}_Predicted': future_predictions.flatten()})

    print(f"Finished predicting {column_name}.")
    return predictions_df, model

# --- Plotting Function ---


def plot_predictions(df, predictions_df, column_name):
    """Plots historical data and future predictions."""
    if predictions_df is None or f'{column_name}_Predicted' not in predictions_df.columns:
        print(f"No predictions to plot for {column_name}.")
        return

    # Find the last valid index for plotting historical data correctly
    last_valid_index_hist = df[column_name].last_valid_index()
    if last_valid_index_hist is None:
        print(f"No historical data to plot for {column_name}.")
        return
    historical_df_to_plot = df.loc[:last_valid_index_hist]

    try:
        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False
    except Exception as e:
        print(f"Warning: Could not set Chinese font for plots. Error: {e}")

    plt.figure(figsize=(12, 6))
    plt.plot(historical_df_to_plot['Date'], historical_df_to_plot[column_name], label=f'Historical {column_name}')
    plt.plot(predictions_df['Date'], predictions_df[f'{column_name}_Predicted'], label=f'Predicted {column_name}', linestyle='--')
    plt.title(f'{column_name} History and Prediction')
    plt.xlabel('Date')
    plt.ylabel(column_name)
    plt.legend()
    plt.grid(True)
    plt.tight_layout()

    # Save plot in the same directory as the script
    plot_filename = os.path.join(script_dir, f'{column_name}_prediction_plot.png')
    try:
        plt.savefig(plot_filename)
        print(f"Prediction plot saved as {plot_filename}")
    except Exception as e:
        print(f"Error saving plot {plot_filename}: {e}")
    plt.close()


# --- Main Execution ---
if __name__ == "__main__":
    print("Loading and preprocessing data for prediction...")
    df_health = load_and_preprocess_data(DATA_PATH)

    if df_health is not None and not df_health.empty:
        metrics_to_predict = ['SleepDuration', 'Weight', 'BodyFatPercentage']
        all_predictions = {}

        for metric in metrics_to_predict:
            preds_df, _ = predict_future(df_health, metric)
            if preds_df is not None:
                plot_predictions(df_health, preds_df, metric)
                print(f"\\nFuture {metric} Predictions:")
                print(preds_df.head())  # Print head for brevity
                all_predictions[metric] = preds_df
            else:
                print(f"Skipping plot/print for {metric} due to prediction failure.")

        # Optional: Combine predictions into a single DataFrame
        if all_predictions:
            final_pred_df = None
            for metric, preds_df in all_predictions.items():
                # Make a copy to avoid modifying the original dict entry
                preds_df_copy = preds_df.copy()
                # Rename the prediction column to just the metric name
                preds_df_renamed = preds_df_copy.rename(columns={f'{metric}_Predicted': metric})
                if final_pred_df is None:
                    final_pred_df = preds_df_renamed  # Start with the first prediction df
                else:
                    # Merge subsequent predictions based on Date
                    final_pred_df = pd.merge(final_pred_df, preds_df_renamed[['Date', metric]], on='Date', how='outer')

            if final_pred_df is not None:
                print("\\n--- Combined Future Predictions ---")
                print(final_pred_df.head())
                # Optional: Save combined predictions to CSV
                combined_csv_path = os.path.join(script_dir, 'combined_predictions.csv')
                try:
                    final_pred_df.to_csv(combined_csv_path, index=False, encoding='utf-8-sig')  # Use utf-8-sig for Excel compatibility
                    print(f"Combined predictions saved to {combined_csv_path}")
                except Exception as e:
                    print(f"Error saving combined predictions to CSV: {e}")

    elif df_health is None:
        print("Failed to load data. Exiting predictor.")
    else:
        print("Data loaded but is empty after processing. Exiting predictor.")
