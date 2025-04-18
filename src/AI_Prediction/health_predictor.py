import pandas as pd
import numpy as np
import re
from datetime import timedelta
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
import matplotlib.pyplot as plt

# --- Configuration ---
DATA_PATH = 'data/Time.csv'
# Number of future days to predict
PREDICT_DAYS = 180
# Sequence length for LSTM
SEQUENCE_LENGTH = 30  # Use last 30 days to predict the next day

# --- Data Loading and Preprocessing ---


def parse_sleep_time(time_str):
    """Converts sleep duration string 'X小时Y分' to total hours."""
    if pd.isna(time_str) or time_str == '':
        return np.nan
    hours = 0
    minutes = 0
    hour_match = re.search(r'(\d+)\s*小时', str(time_str))
    minute_match = re.search(r'(\d+)\s*分', str(time_str))
    if hour_match:
        hours = int(hour_match.group(1))
    if minute_match:
        minutes = int(minute_match.group(1))
    return hours + minutes / 60.0


def load_and_preprocess_data(file_path):
    """Loads and preprocesses the health data from CSV."""
    try:
        # Construct the absolute path relative to the script location
        import os
        script_dir = os.path.dirname(__file__)
        abs_file_path = os.path.join(script_dir, file_path)
        df = pd.read_csv(abs_file_path, encoding='utf-8')  # Try UTF-8 first
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(abs_file_path, encoding='gbk')  # Fallback to GBK
        except Exception as e:
            print(f"Error reading CSV with multiple encodings: {e}")
            return None
    except FileNotFoundError:
        print(f"Error: Data file not found at {abs_file_path}")
        return None

    print("Original columns:", df.columns.tolist())

    # Rename columns for easier access (remove potential newlines)
    df.columns = [col.replace('\r\n', '').replace('\n', '') for col in df.columns]
    print("Cleaned columns:", df.columns.tolist())

    # Select and rename relevant columns
    relevant_cols = {
        '日期': 'Date',
        '睡眠时间': 'SleepDuration',
        '体重': 'Weight',
        '体脂率': 'BodyFatPercentage',
        '健康情况': 'HealthNotes',
        '生活（饮食+社交+运动）': 'LifeNotes'
        # Add '起床时间': 'WakeUpTime' if needed later
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
                # Optional: Fill with a default value like 0 or mean if appropriate
                # df[col] = df[col].fillna(0)

    # Fill missing text data with empty string
    text_cols = ['HealthNotes', 'LifeNotes']
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna('')

    print("\nProcessed Data Head:")
    print(df.head())
    print("\nData Info:")
    df.info()
    print("\nMissing values after processing:")
    print(df.isnull().sum())

    return df

# --- LSTM Model Definition ---


class LSTMPredictor(nn.Module):
    def __init__(self, input_size=1, hidden_layer_size=50, output_size=1):
        super().__init__()
        self.hidden_layer_size = hidden_layer_size
        # Ensure batch_first=True is consistent with how data is fed
        self.lstm = nn.LSTM(input_size, hidden_layer_size, batch_first=True)
        self.linear = nn.Linear(hidden_layer_size, output_size)
        # Hidden state initialization will be handled per batch/sequence

    def forward(self, input_seq):
        # input_seq shape expected: (batch_size, seq_len, input_size)
        # Initialize hidden state for each forward pass (common for stateless LSTM)
        # Shape: (num_layers * num_directions, batch_size, hidden_size)
        batch_size = input_seq.size(0)
        h0 = torch.zeros(1, batch_size, self.hidden_layer_size).to(input_seq.device)
        c0 = torch.zeros(1, batch_size, self.hidden_layer_size).to(input_seq.device)

        lstm_out, _ = self.lstm(input_seq, (h0, c0))
        # lstm_out shape: (batch_size, seq_len, hidden_size)
        # We want the prediction based on the last element of the sequence
        last_time_step_out = lstm_out[:, -1, :]
        predictions = self.linear(last_time_step_out)
        # predictions shape: (batch_size, output_size)
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

    # Convert to tensors, ensure correct shape [num_samples, seq_len, num_features]
    # and [num_samples, num_features_label]
    return torch.stack(sequences), torch.stack(labels)


def predict_future(df, column_name, predict_days=PREDICT_DAYS, seq_length=SEQUENCE_LENGTH):
    """Trains an LSTM model and predicts future values for a given column."""
    if column_name not in df.columns or df[column_name].isnull().all():
        print(f"Column '{column_name}' not found or is all NaN. Skipping prediction.")
        return None, None

    print(f"\n--- Predicting Future {column_name} ---")
    # Find the last valid index for the column BEFORE dropping NaNs for date calculation
    last_valid_index = df[column_name].last_valid_index()
    if last_valid_index is None:
        print(f"Column '{column_name}' contains no valid data. Skipping prediction.")
        return None, None
    last_date = df.loc[last_valid_index, 'Date']
    print(f"Last date with actual data for {column_name}: {last_date}")  # Debug print: Use this date

    # Ensure data is float and handle potential NaNs introduced *after* ffill/bfill (shouldn't happen ideally)
    # Only use data up to the last valid point for training/prediction sequence generation
    data_series = df.loc[:last_valid_index, column_name]
    data = data_series.dropna().values.astype(float)  # Drop NaNs again just in case, though ffill/bfill should handle most

    if len(data) < seq_length + 1:
        print(f"Not enough data points ({len(data)}) after dropping NaN for {column_name} up to {last_date} to create sequences with length {seq_length}. Skipping.")
        return None, None

    # Normalize data
    scaler = MinMaxScaler(feature_range=(-1, 1))
    # Fit scaler ONLY on the actual data used for training
    data_normalized = scaler.fit_transform(data.reshape(-1, 1))
    data_normalized = torch.FloatTensor(data_normalized)  # Shape: [num_samples, 1]

    # Create sequences from the normalized actual data
    sequences, labels = create_sequences(data_normalized, seq_length)
    if sequences is None or len(sequences) == 0:
        print(f"Not enough data to create sequences for {column_name} with length {seq_length}.")
        return None, None

    # Model, Loss, Optimizer
    # input_size = 1 feature (the column itself)
    model = LSTMPredictor(input_size=1, output_size=1)
    loss_function = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    epochs = 150  # Adjust as needed
    batch_size = 16  # Introduce batching

    # Create DataLoader for batching
    from torch.utils.data import TensorDataset, DataLoader
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
            # Model expects (batch_size, seq_len, input_size)
            y_pred = model(seq_batch)  # Shape: [batch_size, 1]
            # Ensure label shape matches output shape (batch_size, output_size)
            # Reshape labels_batch from [batch_size, 1, 1] to [batch_size, 1]
            labels_batch_reshaped = labels_batch.squeeze(1)
            single_loss = loss_function(y_pred, labels_batch_reshaped)  # Use reshaped labels
            single_loss.backward()
            optimizer.step()
            epoch_loss += single_loss.item()
            num_batches += 1

        avg_epoch_loss = epoch_loss / num_batches
        if (i + 1) % 25 == 0:
            print(f'Epoch {i + 1}/{epochs} Average Loss: {avg_epoch_loss:.6f}')

    # Future Prediction Loop
    print(f"Generating future predictions for {column_name}...")
    model.eval()
    future_predictions_normalized = []
    # Start with the last known sequence from the normalized ACTUAL data
    current_sequence_normalized = data_normalized[-seq_length:].view(1, seq_length, 1)
    print(f"Last sequence input shape: {current_sequence_normalized.shape}")  # Debug print
    print(f"Last sequence input (first 5 values normalized): {current_sequence_normalized[0, :5, 0].tolist()}")  # Debug print

    for i in range(predict_days):  # Debug loop index
        with torch.no_grad():
            # Get the prediction for the next step
            next_pred_normalized = model(current_sequence_normalized)
            # next_pred_normalized shape: [1, 1]

            # Store the prediction (scalar value)
            future_predictions_normalized.append(next_pred_normalized.item())

            # Debug print first few normalized predictions
            if i < 5:
                print(f"Normalized prediction {i + 1}: {next_pred_normalized.item()}")

            # Update the sequence for the next prediction:
            # Remove the oldest time step and append the new prediction
            # Keep shape [1, seq_len, 1]
            # Ensure the new prediction tensor has the correct shape for concatenation
            next_pred_tensor = next_pred_normalized.view(1, 1, 1)  # Reshape to [1, 1, 1]
            new_sequence_tensor = torch.cat((current_sequence_normalized[:, 1:, :], next_pred_tensor), dim=1)
            current_sequence_normalized = new_sequence_tensor

    # Inverse transform predictions
    future_predictions = scaler.inverse_transform(np.array(future_predictions_normalized).reshape(-1, 1))
    print(f"First 5 raw predicted values: {future_predictions.flatten()[:5]}")  # Debug print

    # Create future dates starting from the day AFTER the last ACTUAL data point
    # last_date is already determined above
    print(f"Last date in historical data (used for prediction start): {last_date}")  # Re-confirming the date used
    future_dates = pd.date_range(start=last_date + timedelta(days=1), periods=predict_days)
    print(f"First 5 predicted dates: {future_dates[:5].tolist()}")  # Debug print

    predictions_df = pd.DataFrame({'Date': future_dates, f'{column_name}_Predicted': future_predictions.flatten()})

    print(f"Finished predicting {column_name}.")
    return predictions_df, model

# --- Allergy Analysis Function ---


def analyze_allergies(df):
    """Analyzes potential correlations between health notes and life notes."""
    print("\n--- Analyzing Potential Allergy Triggers ---")
    if 'HealthNotes' not in df.columns or 'LifeNotes' not in df.columns:
        print("Warning: 'HealthNotes' or 'LifeNotes' column missing. Skipping allergy analysis.")
        return

    # Focus on digestive issues mentioned in HealthNotes
    # Keywords for potential issues
    issue_keywords = ['拉', '肚子', '泻', '喷射']  # Add more if needed
    # Find days with potential issues
    try:
        # Ensure HealthNotes is string type before using .str
        df['HealthNotes'] = df['HealthNotes'].astype(str)
        issue_days = df[df['HealthNotes'].str.contains('|'.join(issue_keywords), na=False)]
    except Exception as e:
        print(f"Error during allergy analysis keyword search: {e}")
        issue_days = pd.DataFrame()  # Empty dataframe if error

    if issue_days.empty:
        print("No specific health issue keywords found in 'HealthNotes'. Cannot perform allergy analysis.")
        return

    print(f"Found {len(issue_days)} days with potential digestive issues mentioned in HealthNotes.")

    # Look at LifeNotes (food/activity) on the issue day and the day before
    potential_triggers = {}
    for index, row in issue_days.iterrows():
        current_date = row['Date']
        # Look at notes from the same day and the day before
        relevant_notes = ""
        if index > 0:
            prev_day_notes = df.iloc[index - 1]['LifeNotes']
            if pd.notna(prev_day_notes):
                # Ensure prev_day_notes is string
                relevant_notes += f"Prev Day: {str(prev_day_notes)} | "
        current_day_notes = row['LifeNotes']
        if pd.notna(current_day_notes):
            # Ensure current_day_notes is string
            relevant_notes += f"Issue Day: {str(current_day_notes)}"

        health_note = str(row['HealthNotes'])  # Ensure string

        # Simple keyword extraction from LifeNotes (e.g., specific foods)
        # This is very basic and needs refinement based on actual data patterns
        # Example: Extract capitalized words or words after "吃" (ate)
        # Improved regex to handle variations and potential surrounding characters
        foods_mentioned = re.findall(r'吃[了]?[:：]?\s*([\u4e00-\u9fffA-Za-z0-9、，；]+)', relevant_notes)

        print(f"\nDate: {current_date.strftime('%Y-%m-%d')}")
        print(f"  Health Note: {health_note}")
        print(f"  Life Notes (Issue Day & Prev Day): {relevant_notes}")
        print(f"  Potentially Eaten based on '吃': {foods_mentioned}")

        # Count frequency of foods mentioned around issue days
        for food_group in foods_mentioned:
            # Split items separated by common delimiters
            items = re.split('[、，；]', food_group)
            for item in items:
                food_cleaned = item.strip()
                if len(food_cleaned) > 1:  # Avoid single characters or empty strings
                    potential_triggers[food_cleaned] = potential_triggers.get(food_cleaned, 0) + 1

    print("\n--- Potential Trigger Summary (Frequency on/before issue days based on '吃' keyword) ---")
    if potential_triggers:
        # Sort by frequency
        sorted_triggers = sorted(potential_triggers.items(), key=lambda item: item[1], reverse=True)
        for food, count in sorted_triggers:
            print(f"- {food}: {count} times")
    else:
        print("Could not identify specific food items consistently mentioned with '吃' before/on issue days.")

    print("\nDisclaimer: This analysis is based on simple keyword matching ('吃') and correlation.")
    print("It is NOT a medical diagnosis. Consult a healthcare professional for allergy testing.")


# --- Plotting Function ---
def plot_predictions(df, predictions_df, column_name):
    """Plots historical data and future predictions."""
    if predictions_df is None or f'{column_name}_Predicted' not in predictions_df.columns:
        print(f"No predictions to plot for {column_name}.")
        return

    # Ensure matplotlib can handle Chinese characters if needed in titles/labels
    try:
        plt.rcParams['font.sans-serif'] = ['SimHei']  # Or another font like 'Microsoft YaHei'
        plt.rcParams['axes.unicode_minus'] = False  # Handle negative signs correctly
    except Exception as e:
        print(f"Warning: Could not set Chinese font for plots. Characters might not display correctly. Error: {e}")

    plt.figure(figsize=(12, 6))
    plt.plot(df['Date'], df[column_name], label=f'Historical {column_name}')
    plt.plot(predictions_df['Date'], predictions_df[f'{column_name}_Predicted'], label=f'Predicted {column_name}', linestyle='--')
    plt.title(f'{column_name} History and Prediction')
    plt.xlabel('Date')
    plt.ylabel(column_name)
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    # Save or show plot
    # Save plot in the same directory as the script
    import os
    script_dir = os.path.dirname(__file__)
    plot_filename = os.path.join(script_dir, f'{column_name}_prediction_plot.png')
    try:
        plt.savefig(plot_filename)
        print(f"Prediction plot saved as {plot_filename}")
    except Exception as e:
        print(f"Error saving plot {plot_filename}: {e}")
    # plt.show() # Uncomment to display plot directly if running interactively
    plt.close()  # Close the plot figure to free memory


# --- Main Execution ---
if __name__ == "__main__":
    print("Loading and preprocessing data...")
    # Make DATA_PATH relative to the script's location
    df_health = load_and_preprocess_data(DATA_PATH)

    if df_health is not None and not df_health.empty:
        # Predict Sleep Duration
        sleep_preds_df, _ = predict_future(df_health, 'SleepDuration')
        if sleep_preds_df is not None:
            plot_predictions(df_health, sleep_preds_df, 'SleepDuration')
            print("\nFuture Sleep Duration Predictions:")
            print(sleep_preds_df)

        # Predict Weight
        weight_preds_df, _ = predict_future(df_health, 'Weight')
        if weight_preds_df is not None:
            plot_predictions(df_health, weight_preds_df, 'Weight')
            print("\nFuture Weight Predictions:")
            print(weight_preds_df)

        # Predict Body Fat Percentage
        bfp_preds_df, _ = predict_future(df_health, 'BodyFatPercentage')
        if bfp_preds_df is not None:
            plot_predictions(df_health, bfp_preds_df, 'BodyFatPercentage')
            print("\nFuture Body Fat Percentage Predictions:")
            print(bfp_preds_df)

        # Analyze Allergies
        analyze_allergies(df_health)

    elif df_health is None:
        print("Failed to load data. Exiting.")
    else:  # df_health is not None but empty
        print("Data loaded but is empty after processing (e.g., no valid dates). Exiting.")
