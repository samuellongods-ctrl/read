# Gepeto Audio Lab

Separador de voz e instrumentos que roda no seu computador. A página abre no
navegador e pode ser usada também pelo celular ou por outro computador da mesma
rede Wi-Fi, pelo endereço IPv4 e porta (por exemplo `http://192.168.0.15:8000`).
O áudio nunca sai da sua rede.

## Como instalar (Windows)

1. Instale o **Python 3.12** em <https://www.python.org/downloads/> e marque
   **"Add python.exe to PATH"** na primeira tela do instalador.
2. Descompacte esta pasta em um lugar fixo, por exemplo `C:\Users\cococ\Gepeto Audio Lab`.
3. Dê dois cliques em **`instalar.bat`**. Ele cria a pasta `.venv` e baixa tudo
   (PyTorch, audio-separator, yt-dlp e ffmpeg). Leva alguns minutos e usa cerca
   de 2 a 4 GB. Se o computador tiver placa NVIDIA, ele instala a versão para GPU.

## Como usar

1. Dê dois cliques em **`iniciar.bat`**. Uma janela preta mostra os endereços:

   ```
   Neste computador:   http://127.0.0.1:8000
   Na rede (IPv4):     http://192.168.0.15:8000
   ```

   O navegador abre sozinho. Deixe a janela preta aberta enquanto usa.
2. No celular (no mesmo Wi-Fi), digite o endereço "Na rede (IPv4)".
3. Para encerrar, feche a janela preta.

Na primeira vez, o Windows pergunta se o Python pode usar a rede: marque
**Redes privadas** e clique em Permitir. Se o celular não conseguir abrir,
clique com o botão direito em **`liberar-firewall.bat`** e escolha
"Executar como administrador".

### Outra porta

`iniciar.bat --porta 9000` (ou `--host 127.0.0.1` para usar só neste computador).

## Modos de separação

| Modo na página | Faixas | Modelo |
|---|---|---|
| Essencial | Voz, bateria, baixo, outros | Demucs v4 `htdemucs` |
| Banda completa | Voz, bateria, baixo, guitarra, piano, outros | Demucs v4 `htdemucs_6s` |
| Voz e instrumental | Voz, instrumental | MelBand RoFormer (Kim) |
| Voz e instrumental + "separação rápida" | Voz, instrumental | Demucs v4 `htdemucs` |
| Vozes em detalhe | Vocal principal, backing vocal, bateria, baixo, guitarra, piano, outros | `htdemucs_6s` + MelBand RoFormer Karaoke |

Cada modelo é baixado só no primeiro uso (de 80 MB a 900 MB) e fica em
`dados\modelos`. Na CPU, uma música de 4 minutos pode levar de 3 a 20 minutos,
conforme o modo; com GPU NVIDIA é bem mais rápido.

## Baixar do YouTube

Cole o link, escolha MP3 ou MP4 e clique em **Baixar Arquivo**. Com
"Enviar direto para separação" marcado, o MP3 já entra no passo 01. Os arquivos
ficam em `dados\downloads`, e a página mostra um link para salvar no aparelho.
Se um link parar de funcionar, atualize o yt-dlp:

```
.venv\Scripts\python.exe -m pip install -U yt-dlp
```

Baixe apenas conteúdo que você tem direito de usar.

## Onde ficam os arquivos

- `dados\trabalhos\<id>\faixas\` as faixas WAV de cada música
- `dados\downloads\` os downloads do YouTube
- `dados\modelos\` os modelos de IA

Para limpar a biblioteca, feche o app e apague a pasta `dados\trabalhos`.

## Linux ou macOS

```
./instalar.sh
./iniciar.sh            # ou ./iniciar.sh --porta 9000
```

## Problemas comuns

- **"Servidor desconectado" no topo da página:** a janela preta foi fechada. Abra `iniciar.bat` de novo.
- **Erro ao baixar o modelo:** verifique a internet; o download acontece só no primeiro uso.
- **Pouca memória:** feche outros programas. O modo "Vozes em detalhe" é o mais pesado.
- O registro técnico de cada separação fica em `dados\trabalhos\<id>\processamento.log`.
