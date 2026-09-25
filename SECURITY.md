# Security

SwitchOps executa comandos em equipamentos de rede, então trate a aplicação como uma ferramenta administrativa.

## Recomendações

- não exponha o servidor de desenvolvimento Flask diretamente na internet;
- use HTTPS quando houver acesso remoto;
- prefira VPN ou Zero Trust;
- use uma conta SSH dedicada;
- dê à conta somente os privilégios necessários;
- não publique `switchops.db`;
- não publique `config/switches.json`;
- não publique logs;
- mantenha `SWITCHOPS_SECRET_KEY` privada.

Se você encontrar uma falha de segurança, evite publicar credenciais, endereços ou dados de uma rede real em uma issue pública.
