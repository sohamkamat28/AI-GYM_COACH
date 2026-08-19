from services.config.workout_config import PROMPT


class LLMCoach:
    MODEL = "openai/gpt-oss-120b"

    def __init__(self, groq_client=None):
        self.client = groq_client
        self.history = []
        self.system_prompt = PROMPT
        self.last_error = None

    def _fallback_feedback(self, event, issue):
        event_messages = {
            "workout_started": "Let's go! Stay controlled, keep good form, and finish strong.",
            "set_completed": "Great set! Take a breath, reset your form, and keep moving.",
            "workout_completed": "Workout complete! Excellent effort—recover well and come back stronger.",
            "no_pose_detected": "Step fully into the camera frame so I can check your form.",
        }

        if issue:
            return issue

        return event_messages.get(
            event,
            "Keep going! Stay controlled and maintain strong form.",
        )

    def give_feedback(self, event, issue=None):
        prompt = f"Event: {event}"

        if issue:
            prompt += f" Form Issue: {issue}"

        if getattr(self, "client", None) is None:
            return self._fallback_feedback(event, issue)

        messages = [
            {"role": "system", "content": self.system_prompt},
            *self.history[-10:],
            {"role": "user", "content": prompt},
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=messages,
                temperature=0.4,
                reasoning_effort="low",
                max_completion_tokens=256,
            )

            content = response.choices[0].message.content
            text = content.strip() if content else ""
            if not text:
                raise ValueError("Groq returned empty feedback.")

            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)
            return self._fallback_feedback(event, issue)

        self.history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": text},
            ]
        )
        self.history = self.history[-20:]

        return text
