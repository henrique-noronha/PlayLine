Contribuindo com o PlayLine

Obrigado pelo interesse em contribuir com o PlayLine. Este documento
descreve o processo para propor modificações ao projeto.


COMO CONTRIBUIR

1. Faça um fork do repositório para a sua conta do GitHub.

2. Crie uma branch a partir da main com um nome descritivo:
   git checkout -b fix/corrige-reconexao-websocket

3. Realize as alterações na sua branch. Mantenha commits pequenos
   e com mensagens claras descrevendo o que foi feito.

4. Teste suas alterações localmente antes de enviar, verificando
   que o sistema continua operando normalmente.

5. Abra um Pull Request para a branch main do repositório original,
   descrevendo o que foi alterado e o motivo da mudança.

6. Aguarde a análise. Toda modificação proposta será revisada pelo
   autor antes da aprovação. Comentários ou ajustes podem ser
   solicitados durante a revisão.


DIRETRIZES DE CÓDIGO

  - Mantenha a estrutura de três processos (Apresentação, Controle,
    Playout) sem introduzir acoplamento direto entre eles.
  - Não adicione dependências externas sem justificativa. O projeto
    prioriza o menor número possível de dependências.
  - Siga o estilo de código existente no projeto.
  - Documente funções e módulos novos com comentários claros.


O QUE PODE SER CONTRIBUÍDO

  - Correções de bugs e falhas identificadas.
  - Melhorias de desempenho ou estabilidade.
  - Melhorias na interface do operador.
  - Suporte a novos formatos de mídia ou codecs.
  - Documentação e tradução.


O QUE NÃO SERÁ ACEITO

  - Alterações que quebrem o isolamento entre os três processos.
  - Dependências proprietárias ou com licença incompatível com GPLv3.
  - Modificações que exijam etapas de build com Node.js ou similares
    na camada de interface.


REPORTANDO PROBLEMAS

Abra uma Issue no GitHub descrevendo:

  - O que aconteceu e o que era esperado.
  - Passos para reproduzir o problema.
  - Sistema operacional e versão do Python utilizados.
  - Logs relevantes do backend ou do console do navegador.


CONTATO

  PlayLine — Henrique Noronha Fernandes
  henriquenoronha020@gmail.com
  https://github.com/henrique-noronha/playline