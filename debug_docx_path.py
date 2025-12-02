# -*- coding: utf-8 -*-
"""
debug_docx_path.py
专门用来检查当前 Python 眼中的路径和文件情况。
"""

import os
import config  # 复用我们之前写的 config.py

def main():
    print("==== 调试 docx 路径信息 ====\n")

    print(f"BASE_DIR（项目根目录）: {config.BASE_DIR}")
    print(f"DEFAULT_DOCX_PATH（默认题库路径）: {config.DEFAULT_DOCX_PATH}")
    print()

    exists = os.path.exists(config.DEFAULT_DOCX_PATH)
    print(f"os.path.exists(DEFAULT_DOCX_PATH) = {exists}")
    print()

    print("当前 BASE_DIR 目录下的文件和文件夹：")
    try:
        for name in os.listdir(config.BASE_DIR):
            print(" -", name)
    except Exception as e:
        print("列出目录内容时出错：", e)

    print("\n===========================")

    # 允许你输入一个自定义路径再测一次
    user_path = input("\n如果想测试别的路径，请输入完整路径（直接回车跳过）：").strip()
    if user_path:
        print(f"\n你输入的路径：{user_path}")
        print(f"os.path.exists(你输入的路径) = {os.path.exists(user_path)}")
        if os.path.exists(user_path):
            # 顺便看下这个路径是不是一个文件，以及大小
            print("这是一个存在的路径。类型：",
                  "文件" if os.path.isfile(user_path) else "不是普通文件")
            if os.path.isfile(user_path):
                print("文件大小（字节）：", os.path.getsize(user_path))

if __name__ == "__main__":
    main()
