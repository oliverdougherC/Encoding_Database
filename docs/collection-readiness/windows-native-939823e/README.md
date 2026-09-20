# Windows hosted runner communication loss

[Windows job 105998569660](https://github.com/oliverdougherC/Encoding_Database/actions/runs/35480963919/job/105998569660) tested head `939823ead2c052572f9deb5c9f91c85435d5661d` through merge commit `3c89891971af08e401b76a7a6988ad127b59a662`.

GitHub records successful native build completion at 2026-09-20 01:29:58 UTC, then starts the packaged GUI acceptance step. That step never returned a result. The job ended with **failure** and this annotation:

> The hosted runner lost communication with the server. Anything in your workflow that terminates the runner process, starves it for CPU/Memory, or blocks its network access can cause this error.

The annotation establishes lost runner communication; its list of possible causes does not diagnose this run. Terminal metadata still lists the GUI step as in progress and its later steps as pending. The seven-clip console test and immediate diagnostic uploads never ran. No Windows artifact, screenshot, per-phase receipt, or retrievable job log exists. Therefore no preparation Stop, completion, measured Stop, Close, embedded-helper, seven-clip, or visual acceptance claim can be made from this run. The native-build step status alone is insufficient.

The previous outer-budget correction was present: job limit 90 minutes, GUI step limit 31 minutes, per-mode diagnostic uploads before later work. Communication loss prevented this runner from reaching those uploads. No speculative timeout or acceptance relaxation was made after this result. Read-only inspection of the harness found its forced cleanup restricted to discovered descendants of the packaged process with matching creation times; that does not establish the cause of the lost connection. Actual interactive desktop execution remains necessary, with separately identified physical-built packages if the hosted artifacts are unavailable.
