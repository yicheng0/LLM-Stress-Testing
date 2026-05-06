#!/usr/bin/env python3
"""
快速极限压测 - 30秒验证
"""
import subprocess
import sys

cmd = [
    sys.executable, "llm_load_test.py",
    "--concurrency", "500",
    "--duration-sec", "30",
    "--input-tokens", "60000",
]

print("快速极限压测：并发500，60k输入，30秒")
print("=" * 80)
subprocess.run(cmd)
