from google import genai
from config.settings import GEMINI_API_KEY
from utils.logger import logger

class ClassmateChatbot:
    """AI Auto-Reply Chatbot answering peer inquiries about homework status using LLM."""

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def reply_to_peer(self, peer_question: str, context_assignments: list) -> str:
        if not self.client:
            return "Tôi là Trợ lý ELit HUBT AI. Hiện tại chưa thể tự động trả lời vì chưa có API Key."

        prompt = (
            f"Bạn là Trợ lý sinh viên HUBT thông minh, thân thiện.\n"
            f"Bạn học trong nhóm hỏi: '{peer_question}'\n\n"
            f"Thông tin bài tập hiện tại:\n{str(context_assignments)[:1500]}\n\n"
            f"Hãy trả lời ngắn gọn, lịch sự, đúng thông tin bài tập."
        )

        try:
            resp = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return resp.text or "Chào bạn, mình đã ghi nhận câu hỏi."
        except Exception as e:
            logger.error(f"ClassmateChatbot error: {e}")
            return f"Lỗi phản hồi tự động: {str(e)}"

classmate_chatbot = ClassmateChatbot()
