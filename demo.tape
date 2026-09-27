# Demo recording for keybey's README.
#
# Run this on the real machine with an actual Hyprland config, yazi
# keymap override, and Neovim keymaps in place -- the whole point of
# this tool is resolving real ambiguity in real configs, and the demo
# should show that, not placeholder binds.
#
# The scripted moment: searching "l" surfaces yazi's default `l -> enter`
# *and* your own override of it side by side -- the exact "why doesn't
# `l` work" confusion that motivated building this tool.
#
# Install: sudo pacman -S vhs   (or see https://github.com/charmbracelet/vhs)
# Run:     vhs demo.tape
# Output:  demo.gif in this directory -- drop it at the top of README.md
#          right under the title, before "## Features".

Output demo.gif

Set Shell bash
Set FontSize 16
Set Width 1000
Set Height 560
Set Theme "Catppuccin Mocha"
Set Padding 20
Set TypingSpeed 80ms

Type "keybey"
Enter
Sleep 1200ms

# Focus search and type the ambiguous key.
Type "/"
Sleep 300ms
Type "l"
Sleep 1800ms

# Clear back out, search something Hyprland-specific to show cross-source
# results in one list.
Escape
Sleep 400ms
Type "/"
Type "SUPER"
Sleep 1800ms

# Move down and open one bind to show the edit form, then cancel out.
Escape
Down
Down
Sleep 400ms
Enter
Sleep 1500ms
Escape
Sleep 500ms

Type "q"
Sleep 500ms
