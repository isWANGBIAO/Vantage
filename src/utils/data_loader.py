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
    def resolve_data_root(user_home=None, onedrive_env=None):
        env_root = os.environ.get("AI_DATA_ROOT") or os.environ.get("DATA_ROOT")
        if env_root:
            return Path(env_root)

        user_home = user_home or os.path.expanduser("~")
        if onedrive_env is None:
            onedrive_env = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")

        candidates = []
        if onedrive_env:
            candidates.append(Path(onedrive_env) / "Mine")
            candidates.append(Path(onedrive_env))
        candidates.append(Path(user_home) / "OneDrive" / "Mine")
        candidates.append(Path(user_home) / "OneDrive")
        candidates.append(Path(user_home))
        for candidate in candidates:
            if candidate.exists():
                return candidate

        return Config.get_project_root()

    @staticmethod
    def resolve_data_path(filename, user_home=None, onedrive_env=None):
        root = DataLoader.resolve_data_root(user_home=user_home, onedrive_env=onedrive_env)
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
            safe_source = str(excel_file_path).replace("'", "''")
            safe_dest = str(temp_excel_path).replace("'", "''")
            ps_cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Copy-Item -Path '{safe_source}' -Destination '{safe_dest}' -Force"
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
    def get_future_planned_rows(excel_file_path):
        """
        Retrieves future rows with actual content as a formatted summary string.
        Blank future dates are ignored.
        """
        try:
            df = DataLoader.load_excel_data(excel_file_path).copy()
            today = datetime.now().date()
            date_column = "日期" if "日期" in df.columns else "鏃ユ湡"
            weekday_column = "周几" if "周几" in df.columns else None

            df["date_only"] = df[date_column].dt.date
            future_df = df[df["date_only"] > today].sort_values(by=date_column)

            excluded_columns = {"Days", date_column, "date_only"}
            if weekday_column:
                excluded_columns.add(weekday_column)

            lines = []
            for _, row in future_df.iterrows():
                details = []
                for col in future_df.columns:
                    if col in excluded_columns:
                        continue

                    value = row[col]
                    if pd.isna(value):
                        continue

                    value_text = str(value).strip()
                    if not value_text:
                        continue

                    clean_col_name = str(col).replace("\n", " ")
                    details.append(f"{clean_col_name}: {value_text}")

                if not details:
                    continue

                weekday_text = ""
                if weekday_column:
                    weekday_value = row.get(weekday_column)
                    if pd.notna(weekday_value):
                        weekday_text = f"（{str(weekday_value).strip()}）"

                lines.append(
                    f"- {row[date_column].strftime('%Y-%m-%d')}{weekday_text}: " + "；".join(details)
                )

            if not lines:
                return "## Future Planned Items\n\n- 暂无已记录的未来安排\n"

            return "## Future Planned Items\n\n" + "\n".join(lines) + "\n"
        except Exception as e:
            logging.error(f"Error getting future planned rows: {e}")
            return "## Future Planned Items\n\n- 无法获取未来安排\n"

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

        future_planned_rows = DataLoader.get_future_planned_rows(excel_file_path)

        combined_content = f"{prompt_content}\n\n{data_summary}\n\n{future_planned_rows}"

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
    def _build_calendar_info():
        """生成日历信息字符串：公历、农历、节假日、近期节日提醒。"""
        now = datetime.now()
        today = now.date()
        
        # --- 公历 ---
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday_str = weekday_names[now.weekday()]
        solar_str = f"{now.year}年{now.month}月{now.day}日({weekday_str})"
        
        # --- 农历 ---
        lunar_str = ""
        try:
            from zhdate import ZhDate
            lunar = ZhDate.from_datetime(now)
            lunar_str = lunar.chinese()
        except Exception as e:
            logging.warning(f"农历计算失败: {e}")
            lunar_str = "农历信息不可用"
        
        # --- 节假日/工作日 ---
        holiday_str = ""
        try:
            import chinese_calendar
            is_holiday, holiday_name = chinese_calendar.get_holiday_detail(today)
            if is_holiday and holiday_name:
                holiday_str = f"🎉 {holiday_name}"
            elif is_holiday:
                holiday_str = "休息日"
            else:
                if now.weekday() >= 5:
                    holiday_str = "⚠️ 调休工作日"
                else:
                    holiday_str = "工作日"
        except Exception as e:
            logging.warning(f"节假日判断失败: {e}")
            holiday_str = "节假日信息不可用"
        
        # --- 近期节日提醒（未来30天） ---
        upcoming = DataLoader._get_upcoming_festivals(today, days=30)
        upcoming_str = ""
        if upcoming:
            parts = [f"{name}({date.month}/{date.day}, {delta}天后)" if delta > 0 
                     else f"{name}(今天🎉)" 
                     for name, date, delta in upcoming]
            upcoming_str = " | 近期节日: " + ", ".join(parts)
        
        return f"{solar_str} | {lunar_str} | {holiday_str}{upcoming_str}"

    @staticmethod
    def _get_upcoming_festivals(today, days=30):
        """获取未来N天内的公历和农历节日列表。返回 [(名称, 日期, 天数差), ...]"""
        from datetime import timedelta
        
        year = today.year
        
        # 公历固定节日
        solar_festivals = {
            (1, 1): "元旦",
            (2, 14): "情人节",
            (3, 8): "妇女节",
            (3, 12): "植树节",
            (4, 1): "愚人节",
            (5, 1): "劳动节",
            (5, 4): "青年节",
            (6, 1): "儿童节",
            (7, 1): "建党节",
            (8, 1): "建军节",
            (9, 10): "教师节",
            (10, 1): "国庆节",
            (12, 24): "平安夜",
            (12, 25): "圣诞节",
        }
        
        # 农历传统节日 (农历月, 农历日)
        lunar_festivals = {
            (1, 1): "春节",
            (1, 15): "元宵节",
            (5, 5): "端午节",
            (7, 7): "七夕",
            (7, 15): "中元节",
            (8, 15): "中秋节",
            (9, 9): "重阳节",
            (12, 30): "除夕",
            (12, 29): "除夕(小月)",  # 腊月小月时除夕为廿九
        }
        
        results = []
        end_date = today + timedelta(days=days)
        
        # 检查公历节日
        for (m, d), name in solar_festivals.items():
            try:
                from datetime import date
                fest_date = date(year, m, d)
                # 如果今年的已过去，看明年的
                if fest_date < today:
                    fest_date = date(year + 1, m, d)
                if today <= fest_date <= end_date:
                    delta = (fest_date - today).days
                    results.append((name, fest_date, delta))
            except ValueError:
                pass
        
        # 检查农历节日
        try:
            from zhdate import ZhDate
            for (lm, ld), name in lunar_festivals.items():
                try:
                    # 尝试今年的农历日期
                    lunar_date = ZhDate(year, lm, ld)
                    solar_date = lunar_date.to_datetime().date()
                    if solar_date < today:
                        lunar_date = ZhDate(year + 1, lm, ld)
                        solar_date = lunar_date.to_datetime().date()
                    if today <= solar_date <= end_date:
                        delta = (solar_date - today).days
                        results.append((name, solar_date, delta))
                except Exception:
                    pass
        except ImportError:
            pass
        
        # 按日期排序，去重（除夕可能重复）
        results.sort(key=lambda x: x[2])
        seen_names = set()
        unique_results = []
        for name, date, delta in results:
            # 除夕去重：如果已有"除夕"就跳过"除夕(小月)"
            base_name = name.replace("(小月)", "")
            if base_name not in seen_names:
                seen_names.add(base_name)
                unique_results.append((base_name, date, delta))
        
        return unique_results

    @staticmethod
    def get_system_prompt_content():
        base_dir = Config.get_project_root()
        system_prompt_path = base_dir / "Prompt_System.md"
        system_prompt_content = ""
        
        if system_prompt_path.exists():
            system_prompt_content = system_prompt_path.read_text(encoding="utf-8").strip()
        
        # Inject current time context
        current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # Inject calendar info (公历/农历/节假日)
        calendar_info_str = DataLoader._build_calendar_info()
        
        if system_prompt_content:
            if "{current_time}" in system_prompt_content:
                    system_prompt_content = system_prompt_content.replace("{current_time}", current_time_str)
            if "{当前时间}" in system_prompt_content:
                    system_prompt_content = system_prompt_content.replace("{当前时间}", current_time_str)
            if "{calendar_info}" in system_prompt_content:
                    system_prompt_content = system_prompt_content.replace("{calendar_info}", calendar_info_str)
        else:
            system_prompt_content = f"Context: Current Date and Time is {current_time_str}. Calendar: {calendar_info_str}"

        return system_prompt_content
