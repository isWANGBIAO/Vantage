!macro customInstall
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\cli-bin\vantage-cli-path.ps1" -Action Add -Directory "$INSTDIR\resources\cli-bin"'
  Pop $0
  ${If} $0 != "0"
    DetailPrint "Vantage was installed, but its command could not be added to the user PATH."
    MessageBox MB_OK|MB_ICONEXCLAMATION "Vantage could not update the user PATH. You can still run vantage.cmd from the installed resources\cli-bin folder."
  ${EndIf}
!macroend

!macro customUnInstall
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\cli-bin\vantage-cli-path.ps1" -Action Remove -Directory "$INSTDIR\resources\cli-bin"'
  Pop $0
  ${If} $0 != "0"
    DetailPrint "Could not remove the Vantage command directory from the user PATH."
  ${EndIf}
!macroend
