import os

# Load actual files from directory
TEMPLATES_DIR = r'd:\01_RPA\Task\my_app\backend\services\cn_ems\templates'
all_files = os.listdir(TEMPLATES_DIR)

print("=== Directory files (len=%d) ===" % len(all_files))
for i, f in enumerate(all_files):
    print("[%d] %r" % (i, f))

print("\n=== Expected file ===")
expected = "Enter the keyword to filter 输入框.png"
print("%r" % expected)

print("\n=== Check equality ===")
for f in all_files:
    if f == expected or f.strip("'") == expected:
        print("MATCH FOUND: %s" % repr(f))
        break
else:
    print("No match found!")
    
    # Show detailed comparison
    print("\nDetailed comparison:")
    for f in all_files:
        print("  File: %r" % f)
        print("  Len: %d" % len(f))
        print("  Bytes: %r" % f.encode('utf-8'))
        
        stripped = f.strip("'")
        print("  Stripped: %r" % stripped)
        print("  == expected? %s" % (stripped == expected))
