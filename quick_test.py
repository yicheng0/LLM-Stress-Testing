#!/usr/bin/env python3
"""
快速测试脚本 - 单点测试，快速验证功能
"""
import subprocess
import sys

# 单点测试：并发10，时长30秒，输入1000 tokens
cmd = [
    sys.executable, "llm_load_test.py",
    "--concurrency", "10",
    "--duration-sec", "30",
    "--input-tokens", "1000",
    "--enable-stream",
]

print("运行快速测试：并发10，时长30秒，输入1000 tokens")
print("=" * 80)
subprocess.run(cmd)
