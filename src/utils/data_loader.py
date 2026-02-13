import os
import pandas as pd
import subprocess
import tempfile
import logging
from datetime import datetime, timedelta
from pathlib import Path
from src.core.config import Config

class DataLoader:
    @staticmethod
    def resolve_data_root():
        env_root = os.environ.get("AI_DATA_ROOT") or os.environ.get("DATA_ROOT")
        if env_root:
            return Path(env_root)

        candidates = [
            Path(r"C:\Users\97012\OneDrive\Mine"),
            Path("/mnt/c/Users/97012/OneDrive/Mine"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        
        return Config.get_project_root()

    @staticmethod
    def resolve_data_path(filename):
        root = DataLoader.resolve_data_root()
        path = root / filename
        if path.exists():
            return path
            
        # Check Project Root
        project_root = Config.get_project_root()
        path_project = project_root / filename
        if path_project.exists():
            return path_project

        # Check CWD
        fallback = Path.cwd() / filename
        if fallback.exists():
            return fallback
        return path

    @staticmethod
    def _safe_copy_excel(excel_file_path):
        """Copy an Excel file to a temp location for safe reading (handles locked files)."""
        excel_file_path = Path(excel_file_path)
        if not excel_file_path.exists():
            raise FileNotFoundError(f"Excel file not found: {excel_file_path}")

        temp_dir = Path(tempfile.gettempdir())
        temp_excel_path = temp_dir / f"temp_read_{datetime.now().strftime('%f')}.xlsx"

        if os.name == 'nt':
            ps_cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Copy-Item -Path '{str(excel_file_path)}' -Destination '{str(temp_excel_path)}' -Force"
            ]
            subprocess.run(ps_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import shutil
            shutil.copy2(excel_file_path, temp_excel_path)

        return temp_excel_path

    @staticmethod
    def load_excel_data(excel_file_path):
        excel_file_path = Path(excel_file_path)
        temp_excel_path = DataLoader._safe_copy_excel(excel_file_path)
        
        try:
            df = pd.read_excel(temp_excel_path, engine="openpyxl")
        except Exception as e:
            logging.error(f"Error reading excel: {e}")
            raise
        finally:
            if temp_excel_path.exists():
                try:
                    os.remove(temp_excel_path)
                except Exception:
                    pass
        
        if "日期" not in df.columns:
            raise KeyError(f"Excel中缺少'日期'列: {excel_file_path}")
        
        df["日期"] = pd.to_datetime(df["日期"])
        return df

    @staticmethod
    def load_excel_sheets(excel_file_path):
        """
        Load all sheets from an Excel file safely (supports locked files).
        Returns a dict: {sheet_name: DataFrame}
        """
        excel_file_path = Path(excel_file_path)
        temp_excel_path = DataLoader._safe_copy_excel(excel_file_path)

        try:
            sheets = pd.read_excel(temp_excel_path, engine="openpyxl", sheet_name=None)
        except Exception as e:
            logging.error(f"Error reading excel sheets: {e}")
            raise
        finally:
            if temp_excel_path.exists():
                try:
                    os.remove(temp_excel_path)
                except Exception:
                    pass

        return sheets

    @staticmethod
    def get_today_data_row(excel_file_path):
        """
        Retrieves the data row for today (or the latest date) as a formatted string.
        """
        try:
            df = DataLoader.load_excel_data(excel_file_path)
            
            # Find today's row or latest
            today = datetime.now().date()
            # Convert timestamp to date for comparison
            df['date_only'] = df['日期'].dt.date
            
            today_row = df[df['date_only'] == today]
            
            row_str = ""
            if not today_row.empty:
                # Format the row data
                row = today_row.iloc[0]
                row_str = f"本日({today})数据记录：\n"
                for col in df.columns:
                    if col not in ['日期', 'date_only'] and pd.notna(row[col]):
                         row_str += f"- {col}: {row[col]}\n"
            else:
                 # If no data for today, maybe mention latest? Or just empty
                 row_str = f"本日({today})暂无特定数据记录。\n"
                 
            return row_str
        except Exception as e:
            logging.error(f"Error getting today's data row: {e}")
            return "无法获取今日数据记录。"

    @staticmethod
    def get_yesterday_data_row(excel_file_path):
        """
        Retrieves the data row for yesterday as a formatted string.
        """
        try:
            df = DataLoader.load_excel_data(excel_file_path)
            
            yesterday = datetime.now().date() - timedelta(days=1)
            # Convert timestamp to date for comparison
            df['date_only'] = df['日期'].dt.date
            
            yesterday_row = df[df['date_only'] == yesterday]
            
            row_str = ""
            if not yesterday_row.empty:
                # Format the row data
                row = yesterday_row.iloc[0]
                row_str = f"昨日({yesterday})数据记录：\n"
                for col in df.columns:
                    if col not in ['日期', 'date_only'] and pd.notna(row[col]):
                         row_str += f"- {col}: {row[col]}\n"
            else:
                 row_str = f"昨日({yesterday})暂无特定数据记录。\n"
                 
            return row_str
        except Exception as e:
            logging.error(f"Error getting yesterday's data row: {e}")
            return "无法获取昨日数据记录。"

    @staticmethod
    def construct_prompt(prompt_file_path, excel_file_path, days=90):
        prompt_file_path = Path(prompt_file_path)
        excel_file_path = Path(excel_file_path)
        project_mgmt_path = DataLoader.resolve_data_path("Prompt_Project_Management.md")

        if not prompt_file_path.exists():
            raise FileNotFoundError(f"未找到 Prompt 文件: {prompt_file_path}")
        
        df = DataLoader.load_excel_data(excel_file_path)

        prompt_content = prompt_file_path.read_text(encoding="utf-8")

        all_columns = [col for col in df.columns if col != "日期"]

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        filtered_df = df[(df["日期"] >= start_date) & (df["日期"] <= end_date)]
        filtered_df = filtered_df.sort_values(by="日期")

        data_summary = f"## 最近{days}天数据概览\n\n"
        data_summary += (
            f"查询时间段: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}\n\n"
        )

        total_days = (end_date - start_date).days + 1
        days_with_data = len(filtered_df)
        data_summary += f"总天数: {total_days}, 有数据天数: {days_with_data}\n\n"

        if not filtered_df.empty:
            data_summary += "### 详细数据记录\n\n"

            for col in all_columns:
                has_data = filtered_df[col].notna().any()
                if has_data:
                    col_title = col.replace("\n", " ")
                    data_summary += f"#### {col_title}记录\n\n"

                    col_data = filtered_df[["日期", col]].dropna(subset=[col])
                    for _, row in col_data.iterrows():
                        value = row[col]
                        # Special handling logic preserved from original script
                        if col in ["体重", "体脂率"]:
                            data_summary += (
                                f"- {row['日期'].strftime('%Y-%m-%d')}: {value} "
                                f"{'kg' if col == '体重' else '%'}\n"
                            )
                        elif col == "HHH":
                            try:
                                if isinstance(value, str):
                                    num_val = float(value)
                                else:
                                    num_val = float(value)
                                
                                count = abs(num_val)
                                formatted_count = int(count) if count.is_integer() else count
                                
                                if num_val < 0:
                                    display_val = f"手淫 {formatted_count}次"
                                elif num_val > 0:
                                    display_val = f"性关系 {formatted_count}次"
                                else:
                                    display_val = str(value)
                            except (ValueError, TypeError):
                                display_val = str(value)
                            
                            data_summary += f"- {row['日期'].strftime('%Y-%m-%d')}: {display_val}\n"
                        else:
                            data_summary += f"- {row['日期'].strftime('%Y-%m-%d')}: {value}\n"
                    data_summary += "\n"
        else:
            data_summary += "在指定时间段内没有找到任何数据。\n\n"

        data_summary += "### 数据统计摘要\n\n"

        for col in all_columns:
            clean_col_name = col.replace("\n", " ")
            data_summary += f"- {clean_col_name}记录: {filtered_df[col].count()} 天\n"

        data_summary += "\n"

        # Latest Values Logic
        for col in all_columns:
            latest_value = (
                filtered_df[col].dropna().iloc[-1] if filtered_df[col].dropna().any() else None
            )
            latest_date = filtered_df["日期"].max() if not filtered_df.empty else None

            if latest_value is not None:
                clean_col_name = col.replace("\n", " ")
                if col in ["体重", "体脂率"]:
                    data_summary += (
                        f"- 最新{clean_col_name}记录: {latest_date.strftime('%Y-%m-%d')}, "
                        f"{latest_value} {'kg' if col == '体重' else '%'}\n"
                    )
                elif col == "HHH":
                    try:
                        if isinstance(latest_value, str):
                                num_val = float(latest_value)
                        else:
                                num_val = float(latest_value)
                        
                        count = abs(num_val)
                        formatted_count = int(count) if count.is_integer() else count
                        
                        if num_val < 0:
                                display_val = f"手淫 {formatted_count}次"
                        elif num_val > 0:
                                display_val = f"性关系 {formatted_count}次"
                        else:
                                display_val = str(latest_value)
                    except (ValueError, TypeError):
                        display_val = str(latest_value)

                    data_summary += (
                        f"- 最新{clean_col_name}记录: {latest_date.strftime('%Y-%m-%d')}, "
                        f"{display_val}\n"
                    )
                else:
                    data_summary += (
                        f"- 最新{clean_col_name}记录: {latest_date.strftime('%Y-%m-%d')}, "
                        f"{latest_value}\n"
                    )

        combined_content = f"{prompt_content}\n\n{data_summary}"

        if project_mgmt_path.exists():
            pm_content = project_mgmt_path.read_text(encoding="utf-8")
            combined_content += f"\n\n# Project Management Context\n\n{pm_content}"
        
        # Load other markdown files context (Same as original)
        additional_files = {
            "Prompt_Advisor_Requirements.md": "# Advisor Requirements",
            "Prompt_Goals.md": "# Goals",
            "Prompt_Inventory.md": "# Personal Resources & Inventory",
            "Prompt_AI_Instructions.md": "# AI Instructions",
            "Prompt_Scientific_Theory.md": "# Scientific Theory Guidelines"
        }

        for filename, header in additional_files.items():
            file_path = DataLoader.resolve_data_path(filename)
            if file_path.exists():
                 content = file_path.read_text(encoding="utf-8")
                 combined_content += f"\n\n{header}\n\n{content}"

        return combined_content

    @staticmethod
    def get_system_prompt_content():
        base_dir = Config.get_project_root()
        system_prompt_path = base_dir / "Prompt_System.md"
        system_prompt_content = ""
        
        if system_prompt_path.exists():
            system_prompt_content = system_prompt_path.read_text(encoding="utf-8").strip()
        
        # Inject current time context
        current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        if system_prompt_content:
            if "{current_time}" in system_prompt_content:
                    system_prompt_content = system_prompt_content.replace("{current_time}", current_time_str)
            if "{当前时间}" in system_prompt_content:
                    system_prompt_content = system_prompt_content.replace("{当前时间}", current_time_str)
        else:
            system_prompt_content = f"Context: Current Date and Time is {current_time_str}."

        return system_prompt_content
