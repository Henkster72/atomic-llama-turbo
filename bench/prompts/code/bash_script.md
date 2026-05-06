Write a Bash script named `safe-sync.sh`.

Requirements:
- source directory and destination directory are arguments
- fail if either argument is missing
- skip `.git`, `node_modules`, `.cache`, and `dist`
- dry-run by default
- use `rsync`
- add `--apply` to actually sync
- print the exact rsync command before running it

Return only the script in a fenced code block.
