# mini_ark Rainmeter Widgets

Canonical source lives here so Rainmeter skins can be archived with mini_ark without treating the live Rainmeter folder as source control.

## Tender Console

Source:

```text
<Journey checkout>\rainmeter\MiniARKTenderConsole\TenderConsole.ini
<Journey checkout>\rainmeter\MiniARKTenderConsole\@Resources\Scripts\MiniARKAction.ps1
```

Installed copy:

```text
%USERPROFILE%\Documents\Rainmeter\Skins\mini_ark\TenderConsole\TenderConsole.ini
```

Rainmeter config:

```text
mini_ark\TenderConsole
TenderConsole.ini
```

## Controls

- Search strip, Find, and Launch open the local mini_ark Navigator.
- Guide opens `docs\HANDBOOK.md`.
- Manage and Folder open the Journey checkout.
- Diagnostics opens `ark.cmd doctor` in a command window.
- Tests opens `python -m unittest discover -s tests -v`.
- GitHub opens the mini_ark GitHub archive.

This widget is a launcher/control surface. It does not move files, approve proposals, delete anything, or bypass mini_ark's existing safety gates.
