import base64
import hashlib
import time
import streamlit as st

class VoicePipeline:
    VERSION = 5
    MAJOR_EVENTS = {"workout_started", "set_completed", "workout_completed"}
    EVENT_COOLDOWNS = {
        "ongoing_form_check": 8.0,
        "no_pose_detected": 12.0,
    }
    FAILURE_RETRY_DELAY = 10.0
    SPEECH_BUFFER_SECONDS = 0.75

    def __init__(self, llm, tts):
        self.version = self.VERSION
        self.llm = llm
        self.tts = tts
        self.last_spoken_at = 0.0
        self.next_allowed_at = 0.0
        self.last_signature = None
        self.last_error = None

    @staticmethod
    def _estimated_speech_duration(text):
        word_count = len((text or "").split())
        return min(8.0, max(2.0, word_count / 2.5))

    def _find_form_issue(self, exercise, metrics):
        if "issue" in metrics:
            return metrics["issue"]

        if exercise == "Squats":
            depth = metrics.get("depth_status", "")
            back_angle = metrics.get("back_angle", 180)
            
            if depth == "TOO HIGH":
                return "The user's squat is not deep enough — knees are not bending sufficiently."

            if isinstance(back_angle, (int, float)) and back_angle < 130:
                return "The user is leaning too far forward during the squat."

        elif exercise == "Push-ups":
            alignment = metrics.get("body_alignment", "")
            hip_status = metrics.get("hip_status", "")
            
            if alignment == "Poor Form":
                return "The user's body is not straight during the push-up."

            if hip_status == "SAGGING":
                return "The user's hips are sagging down during the push-up."

            if hip_status == "PIKED UP":
                return "The user's hips are too high — lower them to form a straight line."

        elif exercise == "Biceps Curls (Dumbbell)":
            swing = metrics.get("swing_status", "")
            shoulder = metrics.get("shoulder_status", "")
            
            if swing == "SWINGING":
                return "The user is swinging their torso during the curl — keep the body still."

            if shoulder == "ELBOW DRIFTING":
                return "The user's elbow is drifting away from their side during the curl."

        elif exercise == "Shoulder press":
            back_arch = metrics.get("back_arch_status", "")
            extension = metrics.get("extension_status", "")
            
            if back_arch == "Excessive Arch":
                return "The user is arching their lower back excessively during the press."

            if back_arch == "Slight Arch":
                return "Slight back arch detected — encourage the user to brace their core."

        elif exercise == "Lunges":
            balance = metrics.get("balance_status", "")
            
            if balance == "OFF BALANCE":
                return "The user is losing balance during the lunge — feet should be hip-width apart."

        return None
    
    def process_event(self, event, exercise, metrics):
        issue = self._find_form_issue(exercise, metrics)
        now = time.monotonic()
        signature = (event, issue)
        is_major_event = event in self.MAJOR_EVENTS

        if not is_major_event:
            if not issue:
                return None

            if now < self.next_allowed_at:
                return None

            cooldown = self.EVENT_COOLDOWNS.get(event, 8.0)
            if signature == self.last_signature and now - self.last_spoken_at < cooldown:
                return None

        try:
            text = self.llm.give_feedback(event, issue)
            if not text or not text.strip():
                raise ValueError("The coach generated empty feedback.")

            voice = self.tts.speak(text)
            if not voice:
                raise ValueError("Text-to-speech returned no audio.")

            llm_error = getattr(self.llm, "last_error", None)
            self.last_error = (
                f"Groq feedback failed; using built-in coaching: {llm_error}"
                if llm_error
                else None
            )
        except Exception as exc:
            self.last_error = f"Voice generation failed: {exc}"
            self.next_allowed_at = time.monotonic() + self.FAILURE_RETRY_DELAY
            return (None, text) if "text" in locals() else None

        completed_at = time.monotonic()
        self.last_spoken_at = completed_at
        self.last_signature = signature
        self.next_allowed_at = (
            completed_at
            + self._estimated_speech_duration(text)
            + self.SPEECH_BUFFER_SECONDS
        )

        return voice, text


def queue_voice_result(result):
    """Store one coaching result and assign it a unique playback event."""
    if not result:
        return False

    audio_bytes, feedback = result

    if feedback:
        st.session_state.coach_feedback = feedback

    if audio_bytes:
        st.session_state.audio_to_play = audio_bytes
        st.session_state.audio_playback_id = (
            st.session_state.get("audio_playback_id", 0) + 1
        )

    return bool(audio_bytes or feedback)


def autoplay_audio(audio_bytes, playback_id):
    """Play a coaching cue once and show a button only if autoplay is blocked."""
    if not audio_bytes:
        return

    encoded_audio = base64.b64encode(audio_bytes).decode("ascii")
    audio_digest = hashlib.sha256(audio_bytes).hexdigest()[:12]
    event_key = f"coach-{playback_id}-{audio_digest}"

    st.iframe(
        f"""
        <style>
          html, body {{ margin: 0; background: transparent; overflow: hidden; }}
          audio {{ display: none; }}
          #voice-fallback {{
            width: 100%;
            border: 1px solid rgba(245, 166, 35, 0.45);
            border-radius: 0;
            background: rgba(245, 166, 35, 0.08);
            color: #f5a623;
            font: 600 12px/1.2 sans-serif;
            letter-spacing: 0.06em;
            padding: 10px 14px;
            cursor: pointer;
          }}
        </style>
        <audio id="coach-audio" preload="auto"
          src="data:audio/mpeg;base64,{encoded_audio}"></audio>
        <button id="voice-fallback" type="button" hidden>🔊 Play AI coach</button>
        <script>
          (() => {{
            const eventKey = {event_key!r};
            const audio = document.getElementById("coach-audio");
            const fallback = document.getElementById("voice-fallback");

            const wasPlayed = () => {{
              try {{ return window.parent.__aiGymLastVoiceEvent === eventKey; }}
              catch (_) {{ return false; }}
            }};

            const markPlayed = () => {{
              try {{ window.parent.__aiGymLastVoiceEvent = eventKey; }}
              catch (_) {{ /* The current iframe will still finish playback. */ }}
            }};

            const hideFallback = () => {{
              fallback.hidden = true;
            }};

            const showFallback = () => {{
              fallback.hidden = false;
            }};

            const play = () => {{
              const attempt = audio.play();
              if (!attempt) {{
                markPlayed();
                hideFallback();
                return;
              }}

              attempt.then(() => {{
                markPlayed();
                hideFallback();
              }}).catch(showFallback);
            }};

            fallback.addEventListener("click", play);
            audio.addEventListener("ended", hideFallback);

            if (wasPlayed()) hideFallback();
            else play();
          }})();
        </script>
        """,
        height="content",
        tab_index=-1,
    )
