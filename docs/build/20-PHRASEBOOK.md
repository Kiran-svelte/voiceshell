# VoiceShell — What you can say (verified working)

Every phrase below was run on a fresh demo workspace on 2026-10-24 and **checked to do the right thing**. 50 of 50 passed. Only passing phrases are listed.

In **voice mode**: hold Enter, say the phrase, release. Say file names as words — *notes dot t x t*.
**⚡ = instant** (built-in, always works). **🤖 = planned by the local AI** (works, takes a few seconds).

## Look around

- ⚡ “what's in downloads”
- ⚡ “list the files in the logs folder”
- ⚡ “show me what's inside projects”
- 🤖 “what files are in the tmp folder”
- ⚡ “list the files here”
- ⚡ “where am I”

## Count

- ⚡ “how many files are in downloads”
- ⚡ “count the files in the logs folder”
- ⚡ “how many pdf files are in downloads”
- ⚡ “how many log files are in logs”

## Find by type

- ⚡ “find all the pdf files”
- ⚡ “show me every log file”
- ⚡ “find all the csv files”
- ⚡ “find all the image files”

## Space

- ⚡ “what's taking up space in my downloads folder”
- ⚡ “what's the biggest file in downloads”
- ⚡ “show me the biggest files in the logs folder”
- ⚡ “how much disk space do I have”

## Read a file

- ⚡ “read notes.txt”
- ⚡ “show me what todo.md says”
- ⚡ “how many lines are in notes.txt”
- ⚡ “show me the first line of todo.md”
- ⚡ “search for the word dentist in notes.txt”

## Make a folder

- ⚡ “make a folder called reports”
- ⚡ “create a new folder named photos”

## Make a file

- ⚡ “create a file called ideas.txt”
- ⚡ “create a file called hello.txt and write hi there in it”
- ⚡ “make a file called todo2 and write buy milk in it”

## Copy

- 🤖 “copy notes.txt to notes-backup.txt”
- 🤖 “make a copy of todo.md as todo-copy.md”

## Rename

- 🤖 “rename report-old.txt to report-2023.txt”
- 🤖 “change the name of todo.md to tasks.md”

## Move

- 🤖 “move budget.csv from downloads into the projects folder”
- ⚡ “make a folder called pdfs and move all the pdfs from downloads into it”

## Compress

- 🤖 “compress the projects folder into an archive called projects-backup”

## Delete

- ⚡ “delete report-old.txt”
- ⚡ “delete the file called status.txt”
- ⚡ “delete all the log files in the logs folder”
- ⚡ “delete the temporary files in the tmp folder”
- 🤖 “get rid of report-old.txt”

## Undo

- ⚡ “undo that  (after a delete)”

## Move around

- ⚡ “go to the logs folder”
- ⚡ “go to downloads”
- ⚡ “go up  (from a sub-folder)”

## Conversation

- 🤖 “what can you do”
- 🤖 “delete it”

## Safely refused

- 🤖 “run the script I downloaded”
- 🤖 “download python from the internet”
- 🤖 “tell me a joke”
- 🤖 “copy notes.txt to the desktop”

## How it keeps you safe (every time)
- It works **only inside the `workspace` folder** — never your real files, drives, or the internet.
- Before anything that **changes or deletes**, it shows the exact effect and waits for your **yes**.
- Deleted files go to a trash you can bring back for 24 hours — say **“undo that”**.
- It ignores instructions hidden inside files, and refuses scripts, downloads, and chit-chat.

## Tips for phrasing
- Name the folder: *“...in the logs folder”*, *“...in downloads”*.
- For files with no extension spoken, it assumes `.txt` (e.g. *“create a file called ideas”* → `ideas.txt`).
- To work inside a sub-folder, either name it (*“...in downloads”*) or go there first (*“go to downloads”*).
- Answer confirmations naturally: *“yes”*, *“yeah”*, *“okay”*, *“go ahead”*; silence or *“no”* cancels.
