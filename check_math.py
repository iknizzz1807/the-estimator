import re

with open("README.md", "r", encoding="utf-8") as f:
    text = f.read()

d = chr(36)
double_d = d + d

blocks = re.findall(r"\$\$.*?\$\$", text, flags=re.DOTALL)
print(f"Number of $$ blocks: {len(blocks)}")

no_blocks = re.sub(r"\$\$.*?\$\$", "", text, flags=re.DOTALL)
singles = no_blocks.count(d)
print(f"Number of single dollars: {singles}")

lines = text.splitlines()
in_block = False
for idx, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith("$$"):
        in_block = not in_block
        continue
    if in_block:
        continue
    cnt = line.count(d)
    if cnt % 2 != 0:
        print(f"Line {idx} (count {cnt}): {ascii(line)}")
