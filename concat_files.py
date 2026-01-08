#!/usr/bin/env python3
"""
Concatenate all .html and .py files from current directory and subdirectories into a single txt file.
"""

import os
from pathlib import Path


def concat_files(output_file="output.txt"):
    """Concatenate all .html and .py files to a single txt file."""

    extensions = ['.html', '.py']
    file_count = 0

    with open(output_file, 'w', encoding='utf-8') as out:
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for file in files:
                file_path = Path(root) / file

                if file_path.suffix.lower() in extensions:
                    file_count += 1

                    out.write(f"\n{'=' * 80}\n")
                    out.write(f"FILE: {file_path}\n")
                    out.write(f"{'=' * 80}\n\n")

                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            out.write(content)
                            out.write('\n')
                    except Exception as e:
                        out.write(f"[ERROR reading file: {e}]\n")
                        print(f"Error reading {file_path}: {e}")

    print(f"Successfully concatenated {file_count} files to {output_file}")


if __name__ == "__main__":
    concat_files()
