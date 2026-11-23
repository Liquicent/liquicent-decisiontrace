# 60-second README GIF. Record with https://github.com/charmbracelet/vhs:  vhs docs/demo.tape
Output docs/demo.gif
Set FontSize 16
Set Width 1200
Set Height 720
Set TypingSpeed 40ms
Env DT_HOME "/tmp/dt-demo"

Type "uv run python examples/refund_agent.py" Enter
Sleep 3s
Type "dt log" Enter
Sleep 2s
Type `dt why "$(dt log -n 1 | awk '{print $3}')"` Enter
Sleep 8s
Type `dt ask "which refunds needed an exception?"` Enter
Sleep 4s
Type "dt verify" Enter
Sleep 3s
