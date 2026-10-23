@echo off
chcp 65001 >nul
rem Cria o atalho "Gepeto Audio Lab" na Area de Trabalho (abre o app com um clique, minimizado).
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop');$s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\Gepeto Audio Lab.lnk');$s.TargetPath='%~dp0iniciar.bat';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;$s.Description='Gepeto Audio Lab';$s.IconLocation='%~dp0gepeto.ico';$s.Save();Write-Host ('Atalho criado em: '+$d+'\Gepeto Audio Lab.lnk')"
if errorlevel 1 (
  echo Nao foi possivel criar o atalho.
) else (
  echo Pronto: use o atalho "Gepeto Audio Lab" na Area de Trabalho.
  echo Ele abre o app minimizado e o navegador sozinho. Para encerrar, feche a janela minimizada na barra de tarefas.
)
pause
