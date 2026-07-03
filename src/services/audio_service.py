import logging
import os
import subprocess

import requests

from src.core.config import Config


class AudioTranscriptionError(RuntimeError):
    def __init__(self, message, *, configuration_error=False):
        super().__init__(message)
        self.configuration_error = configuration_error


class AudioService:
    @staticmethod
    def convert_to_wav(input_path):
        """Convert browser-recorded audio to a transcription-friendly WAV file."""
        try:
            output_path = os.path.splitext(input_path)[0] + "_converted.wav"
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                output_path,
            ]

            logging.info("Converting audio: %s", " ".join(cmd))
            result = subprocess.run(cmd, capture_output=True, timeout=30)

            if result.returncode != 0:
                logging.error(
                    "FFmpeg error: %s",
                    result.stderr.decode("utf-8", errors="replace"),
                )
                return None

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logging.info("Converted audio saved to: %s", output_path)
                return output_path

            logging.error("FFmpeg conversion produced empty or no file")
            return None
        except FileNotFoundError:
            logging.error("FFmpeg not found. Please install ffmpeg and add it to PATH.")
            return None
        except Exception as exc:
            logging.error("Audio conversion error: %s", exc)
            return None

    @staticmethod
    def _resolve_transcription_config(base_url=None, api_key=None, model=None):
        Config.load_env()
        resolved_base_url = (
            base_url
            or Config.get("VANTAGE_TRANSCRIBE_BASE_URL")
            or Config.get("SILICONFLOW_BASE_URL")
            or ""
        ).strip()
        resolved_api_key = (
            api_key
            or Config.get("VANTAGE_TRANSCRIBE_API_KEY")
            or Config.get("SILICONFLOW_API_KEY")
            or ""
        ).strip()
        resolved_model = (
            model
            or Config.get("VANTAGE_TRANSCRIBE_MODEL")
            or Config.get("SILICONFLOW_AUDIO_MODEL")
            or "FunAudioLLM/SenseVoiceSmall"
        ).strip()

        missing = []
        if not resolved_base_url:
            missing.append("base URL")
        if not resolved_api_key:
            missing.append("API key")
        if not resolved_model:
            missing.append("model")
        if missing:
            raise AudioTranscriptionError(
                f"Missing voice transcription configuration: {', '.join(missing)}",
                configuration_error=True,
            )

        return {
            "base_url": resolved_base_url,
            "api_key": resolved_api_key,
            "model": resolved_model,
        }

    @staticmethod
    def transcribe(file_path, *, base_url=None, api_key=None, model=None):
        """Transcribe an audio file through the configured voice provider."""
        config = AudioService._resolve_transcription_config(
            base_url=base_url,
            api_key=api_key,
            model=model,
        )

        logging.info("Transcribing file: %s", file_path)
        file_ext = os.path.splitext(file_path)[1].lower()
        actual_file = file_path
        converted_file = None

        if file_ext not in [".wav", ".mp3", ".flac", ".m4a"]:
            logging.info("Detected %s audio, converting to WAV.", file_ext or "unknown")
            converted_file = AudioService.convert_to_wav(file_path)
            if converted_file:
                actual_file = converted_file
            else:
                logging.warning("Conversion failed, trying original file.")

        url = config["base_url"].rstrip("/") + "/audio/transcriptions"
        headers = {"Authorization": f"Bearer {config['api_key']}"}

        try:
            mime_type = "audio/wav"
            if actual_file.endswith(".mp3"):
                mime_type = "audio/mpeg"
            elif actual_file.endswith(".flac"):
                mime_type = "audio/flac"
            elif actual_file.endswith(".m4a"):
                mime_type = "audio/mp4"
            elif actual_file.endswith(".webm"):
                mime_type = "audio/webm"

            logging.info("Sending audio to voice provider: %s (MIME: %s)", actual_file, mime_type)

            with open(actual_file, "rb") as audio_file:
                files = {
                    "file": (os.path.basename(actual_file), audio_file, mime_type),
                    "model": (None, config["model"]),
                }
                response = requests.post(url, headers=headers, files=files, timeout=60)

            logging.info("Voice provider response status: %s", response.status_code)
            if not response.ok:
                details = response.text.strip()
                raise AudioTranscriptionError(
                    f"Voice provider returned HTTP {response.status_code}: {details}",
                )

            result = response.json()
            text = str(result.get("text", "")).strip()
            logging.info(
                "Transcription result: %s",
                f"{text[:100]}..." if len(text) > 100 else text,
            )
            return text
        except AudioTranscriptionError:
            raise
        except Exception as exc:
            raise AudioTranscriptionError(f"Audio transcription failed: {exc}") from exc
        finally:
            if converted_file and os.path.exists(converted_file):
                try:
                    os.remove(converted_file)
                    logging.info("Cleaned up converted file: %s", converted_file)
                except OSError:
                    pass
