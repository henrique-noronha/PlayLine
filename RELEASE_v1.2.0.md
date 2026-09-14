# PlayLine v1.2.0

Esta versão fecha o ciclo que começou na v1.1.0 com um objetivo claro: **tirar a configuração do código e colocar na mão do operador**, e deixar o sistema capaz de ficar no ar sem ninguém por perto.

Agora a emissora troca a senha, escolhe a pasta dos vídeos e monta a lista de cidades pela própria interface. O playout ganhou transição suave entre clipes, entrada de câmera ao vivo, um aplicativo para enviar vídeos pela rede e um conjunto de proteções que recuperam a transmissão sozinho depois de uma falha.

---

## Novidades

### Configurações na interface

Novo item **Configurações** no menu do Painel de Controle, organizado em abas:

- **Usuário e senha**: troque as credenciais confirmando o usuário e a senha atuais, sem precisar de suporte técnico. A senha passa a ser guardada de forma cifrada (PBKDF2-SHA256 com salt), nunca em texto legível. Ao alterar, as outras sessões abertas caem e precisam entrar de novo.
- **Pasta da biblioteca**: aponte o PlayLine para qualquer pasta do computador, inclusive um disco externo, com seletor nativo do Windows. Os clipes já no roteiro continuam tocando normalmente.
- **Cidades**: monte a lista que aparece no seletor de hora e temperatura, com busca na base da OpenWeatherMap e limite de 30 cidades. Deixe apenas as que a emissora usa.
- **Duração do FTB**: tempo do escurecimento da transição, de 0,2 a 3 segundos.

### Transições CUT e FTB

A troca entre clipes agora pode ser corte seco (**CUT**) ou fade to black (**FTB**), com a nomenclatura usada em switchers e automações de TV.

- Botão no cabeçalho do Roteiro alterna o modo de toda a grade
- No menu de engrenagem de cada clipe, defina a transição só daquele item
- No modo FTB, imagem e áudio descem juntos até o preto e voltam no clipe seguinte

### Entrada de vídeo ao vivo

- Câmeras, placas de captura e vídeos ou transmissões do YouTube entram no roteiro como itens normais
- Novo quadrante ao lado do Roteiro mostra a prévia da fonte antes de ela ir ao ar
- Reconexão automática quando o sinal cai, com registro no histórico

### PlayIngest

Novo aplicativo (`PlayIngest.exe`) para enviar vídeos à biblioteca a partir de qualquer máquina da rede, sem pendrive e sem acesso à pasta compartilhada. Informe o IP do servidor, faça login com as mesmas credenciais, escolha a subpasta e arraste os arquivos. Ele confere espaço em disco e permissões antes de gravar.

### Operação contínua, sem operador

- **Retomada após queda de energia**: ao religar, o PlayLine volta no item que estava no ar
- **Reabertura automática do player** se ele for encerrado no meio de um clipe
- **Watchdog de clipe travado**: se a reprodução parar de avançar, o sistema segue para o próximo item
- **Supervisor do servidor** dentro da janela do aplicativo, que o reinicia se ele cair
- **`install_autostart.bat`**: registra o PlayLine para iniciar junto com o Windows

### Segurança

- As conexões em tempo real (WebSocket) passaram a exigir sessão válida. Antes, qualquer máquina que alcançasse a porta do servidor podia controlar o playout sem senha.
- Sessão de 8 horas por máquina, com retorno automático à tela de login quando expira

### Roteiro

- Nova coluna **Categoria**, com as três primeiras letras da pasta do clipe na biblioteca (COM para Comerciais, por exemplo). Itens ao vivo aparecem como YT ou CAM.
- Modo **Repetir**, que reinicia a grade ao terminar
- Troca entre clipes sem tela preta, com o próximo item pré-carregado

### Desempenho

- **YouTube mais rápido**: a resolução do endereço de transmissão caiu de cerca de 13 segundos para cerca de 3, e o stream da próxima live é preparado enquanto o clipe atual ainda toca
- **Prévia da saída** captada por GPU quando há monitor secundário, com retomada automática se a captura falhar
- Buffer de leitura ampliado, o que absorve melhor as oscilações de rede em transmissões ao vivo

---

## Correções

- Reprodução do YouTube parava com erro 403 por causa de uma versão antiga do yt-dlp presa no aplicativo. O build agora atualiza a dependência sempre.
- O medidor de volume parava de funcionar ao fechar e reabrir apenas a interface
- A posição do clipe não era restaurada ao reabrir a interface, e os contadores do painel ficavam congelados
- Temperatura podia vir da cidade errada quando havia homônimas (existem cinco "Palmas" no Brasil). A consulta agora usa as coordenadas da cidade escolhida.
- Configurações por clipe (automação de overlays, tipo do item) eram perdidas ao reiniciar o sistema
- A prévia da saída caía para o modo alternativo em definitivo após uma falha passageira da captura
- Disputa pelo dispositivo de captura na hora de entrar no ar, que derrubava a câmera na primeira vez
- Popups de automação abriam longe do clique
- Em desenvolvimento, o checkpoint de recuperação era gravado num arquivo diferente do usado pelo servidor, o que fazia a recuperação nunca funcionar fora do build

---

## Como atualizar a partir da v1.1.0

1. Feche o PlayLine pelo botão X, escolhendo **Fechar interface e player**
2. Extraia o novo `.zip` em uma pasta nova
3. Copie da instalação anterior para a nova:
   - a pasta `Biblioteca` (ou aponte para a pasta antiga em Configurações)
   - a pasta `logos`
   - o arquivo `playline.db`, se quiser manter roteiro e histórico
4. Abra o `PlayLine.exe` e entre com as credenciais de sempre
5. **Troque a senha padrão** em Configurações, na aba Usuário e senha

O banco de dados é atualizado automaticamente na primeira execução. Não é preciso reinstalar nada além do aplicativo.

---

## Requisitos

- Windows 10 64-bit (versão 1903 ou superior) ou Windows 11
- [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) e [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/), ambos gratuitos e normalmente já presentes
- Monitor ou placa de saída para o sinal de exibição

---

**Arquivo:** `Playline.v1.2.0.zip`
**SHA-256:** `9ec2dd49f26dd9a2d585ede49cd0aaf1b11afe1b3db4e0155d7fd6d8deef8341`

Inclui servidor, daemon de vídeo, interface, PlayLine-Client e PlayIngest.
