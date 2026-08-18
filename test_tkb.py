#!/usr/bin/env python3
"""
Script chạy thử nghiệm tính năng Tra cứu Thời khóa biểu HUBT độc lập (không cần chạy bot Telegram).

Cách dùng:
1. Chạy trực tiếp với tham số lớp:
   python3 test_tkb.py th30.10

2. Hoặc chạy ở chế độ tương tác nhập từ bàn phím:
   python3 test_tkb.py
"""

import sys
import asyncio
from services.schedule_service import schedule_service

async def main():
    print("=" * 60)
    print("🎓 CÔNG CỤ TRA CỨU THỜI KHÓA BIỂU HUBT (ITC HUBT)")
    print("=" * 60)

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:]).strip()
    else:
        try:
            query = input("\n👉 Nhập tên khóa / ngành / lớp cần tra cứu (ví dụ: th30.10, th30, CNTT): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nĐã hủy.")
            return

    if not query:
        print("⚠️ Bạn chưa nhập từ khóa!")
        return

    print(f"\n⏳ Đang gửi yêu cầu tra cứu tới itc.hubt.edu.vn cho từ khóa: '{query}'...")
    result = await schedule_service.fetch_schedule(query)

    if not result.get("success"):
        print(f"\n❌ LỖI: {result.get('error')}")
        return

    messages = schedule_service.format_schedule_messages(result)
    print("\n" + "=" * 60)
    print("📋 KẾT QUẢ THỜI KHÓA BIỂU:")
    print("=" * 60)
    for msg in messages:
        # In kết quả định dạng rõ ràng
        print(msg)
        print("-" * 60)

if __name__ == "__main__":
    asyncio.run(main())
