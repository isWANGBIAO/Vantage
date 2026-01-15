import os
import requests
import logging
from src.core.config import Config

class AudioService:
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
            
        url = base_url.rstrip("/") + "/audio/transcriptions"
        
        # Model: fun-audio-llm/sensevoice-small is a common choice on SiliconFlow
        model = "FunAudioLLM/SenseVoiceSmall" 
        
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        try:
            with open(file_path, "rb") as f:
                files = {
                    "file": (os.path.basename(file_path), f, "audio/wav"),
                    "model": (None, model)
                }
                # Note: requests sends multipart/form-data when files is present
                response = requests.post(url, headers=headers, files=files, timeout=60)
                
            if not response.ok:
                logging.error(f"API Error details: {response.text}")
                
            response.raise_for_status()
            result = response.json()
            return result.get("text", "")
            
        except Exception as e:
            logging.error(f"Transcription error: {e}")
            return None
