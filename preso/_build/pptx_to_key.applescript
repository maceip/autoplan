-- Convert the generated deck to a native Keynote file.
-- Requires macOS Automation permission for Keynote (System Settings >
-- Privacy & Security > Automation). Without it every Apple event returns
-- -10004 and this script fails at the first line.
set srcPath to "/Users/mac/autoplan/preso/FlashHandoff.pptx"
set dstPath to "/Users/mac/autoplan/preso/FlashHandoff.key"

tell application id "com.apple.Keynote"
	set theDoc to open (POSIX file srcPath)
	delay 1
	save theDoc in (POSIX file dstPath)
	delay 1
	close theDoc saving no
end tell

return "wrote " & dstPath
