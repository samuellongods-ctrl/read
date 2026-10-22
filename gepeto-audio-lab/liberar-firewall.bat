@echo off
chcp 65001 >nul
rem Libera a porta 8000 para outros aparelhos da rede (precisa ser administrador).
net session >nul 2>nul
if errorlevel 1 (
  echo Clique com o botao direito neste arquivo e escolha "Executar como administrador".
  pause
  exit /b 1
)
set "PORTA=%~1"
if "%PORTA%"=="" set "PORTA=8000"
netsh advfirewall firewall delete rule name="Gepeto Audio Lab" >nul 2>nul
netsh advfirewall firewall add rule name="Gepeto Audio Lab" dir=in action=allow protocol=TCP localport=%PORTA% profile=private
echo Porta %PORTA% liberada nas redes privadas.
pause
