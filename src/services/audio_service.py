import os
import requests
import logging
import subprocess
import tempfile
from src.core.config import Config

class AudioService:
    @staticmethod
    def convert_to_wav(input_path):
        """
        Convert audio file to WAV format using ffmpeg.
        Returns the path to the converted file, or None if conversion fails.
        """
        try:
            # 生成临时 wav 文件路径
            output_path = os.path.splitext(input_path)[0] + "_converted.wav"
            
            # 使用 ffmpeg 转换
            cmd = [
                "ffmpeg", "-y",  # 覆盖输出文件
                "-i", input_path,
                "-ar", "16000",  # 采样率 16kHz（语音识别常用）
                "-ac", "1",      # 单声道
                "-f", "wav",
                output_path
            ]
            
            logging.info(f"Converting audio: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            
            if result.returncode != 0:
                logging.error(f"FFmpeg error: {result.stderr.decode('utf-8', errors='replace')}")
                return None
                
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logging.info(f"Converted audio saved to: {output_path}")
                return output_path
            else:
                logging.error("FFmpeg conversion produced empty or no file")
                return None
                
        except FileNotFoundError:
            logging.error("FFmpeg not found. Please install ffmpeg and add it to PATH.")
            return None
        except Exception as e:
            logging.error(f"Audio conversion error: {e}")
            return None
    
    @staticmethod
    def transcribe(file_path):
        """
        Transcribe audio file using SiliconFlow API.
        """
        Config.load_env()
        base_url = Config.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
        api_key = Config.get("SILICONFLOW_API_KEY")
        
        if not api_key:
            logging.error("Missing environment variable: SILICONFLOW_API_KEY")
            return None
        
        logging.info(f"Transcribing file: {file_path}")
        
        # 检查文件格式，如果不是 wav 则转换
        file_ext = os.path.splitext(file_path)[1].lower()
        actual_file = file_path
        converted_file = None
        
        if file_ext not in ['.wav', '.mp3', '.flac', '.m4a']:
            logging.info(f"Detected non-standard format ({file_ext}), converting to WAV...")
            converted_file = AudioService.convert_to_wav(file_path)
            if converted_file:
                actual_file = converted_file
            else:
                logging.warning("Conversion failed, trying original file anyway...")
            
        url = base_url.rstrip("/") + "/audio/transcriptions"
        
        # Audio transcription remains pinned to SiliconFlow configuration.
        model = Config.get("SILICONFLOW_AUDIO_MODEL", "FunAudioLLM/SenseVoiceSmall")
        
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        try:
            # 根据文件扩展名设置 MIME 类型
            mime_type = "audio/wav"
            if actual_file.endswith('.mp3'):
                mime_type = "audio/mpeg"
            elif actual_file.endswith('.flac'):
                mime_type = "audio/flac"
            elif actual_file.endswith('.m4a'):
                mime_type = "audio/mp4"
            elif actual_file.endswith('.webm'):
                mime_type = "audio/webm"
            
            logging.info(f"Sending to API: {actual_file} (MIME: {mime_type})")
            
            with open(actual_file, "rb") as f:
                files = {
                    "file": (os.path.basename(actual_file), f, mime_type),
                    "model": (None, model)
                }
                response = requests.post(url, headers=headers, files=files, timeout=60)
                
            logging.info(f"API Response status: {response.status_code}")
            
            if not response.ok:
                logging.error(f"API Error details: {response.text}")
                
            response.raise_for_status()
            result = response.json()
            text = result.get("text", "")
            logging.info(f"Transcription result: {text[:100]}..." if len(text) > 100 else f"Transcription result: {text}")
            return text
            
        except Exception as e:
            logging.error(f"Transcription error: {e}")
            return None
        finally:
            # 清理转换后的临时文件
            if converted_file and os.path.exists(converted_file):
                try:
                    os.remove(converted_file)
                    logging.info(f"Cleaned up converted file: {converted_file}")
                except:
                    pass
