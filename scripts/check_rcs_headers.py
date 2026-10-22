from pathlib import Path
p1 = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\1.rcs")
p2 = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\2.rcs")

b1 = p1.read_bytes()[:64]
b2 = p2.read_bytes()[:64]

print("1.rcs header:", b1[:16])
print("2.rcs header:", b2[:16])
print("Same header magic?", b1[:16] == b2[:16])
