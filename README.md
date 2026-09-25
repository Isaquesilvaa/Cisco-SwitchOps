<div align="center">

# <img src="https://cdn.simpleicons.org/cisco/1BA0D7" width="34"/> SwitchOps

### Interface web para operação, monitoramento e automação de switches Cisco

![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Web_App-000000?logo=flask&logoColor=white)
![Cisco](https://img.shields.io/badge/Cisco-IOS-1BA0D7?logo=cisco&logoColor=white)
![Netmiko](https://img.shields.io/badge/Netmiko-SSH-2C3E50)
![SQLite](https://img.shields.io/badge/SQLite-RBAC-003B57?logo=sqlite&logoColor=white)
![Status](https://img.shields.io/badge/status-em_desenvolvimento-yellow)

</div>

---

## 🖧 Sobre o projeto

O **SwitchOps** começou por um motivo bem simples: eu queria parar de entrar no CLI toda hora só para fazer coisas básicas em switch.

Consultar uma porta, remover sticky MAC, procurar um dispositivo, dar shutdown/no shutdown...

Tudo isso funciona muito bem pelo terminal, mas em algumas situações é mais rápido ter uma interface pronta para a operação do dia a dia.

Então comecei fazendo uma ferramenta simples em Python.

Aí fui mexendo.

Depois coloquei Flask.

Depois Netmiko.

Depois painel de portas.

Depois monitoramento.

Quando fui ver, já tinha virado isso aqui. kkkkk

O objetivo do projeto é continuar simples:

> facilitar operações comuns em switches Cisco sem tentar substituir o CLI.

Para troubleshooting mais pesado, configuração avançada e diagnóstico profundo, continuo achando o terminal melhor.

Esse projeto ainda está em desenvolvimento e muita coisa eu ainda estou aprendendo no caminho.

Se alguém quiser testar em outro modelo de switch, corrigir alguma coisa, melhorar um parser ou simplesmente dar uma ideia, pode abrir uma **Issue** ou mandar um **Pull Request**.

Ajuda é bem-vinda, principalmente porque equipamentos e versões diferentes do IOS podem responder de formas diferentes.

---

## 🔌 O que ele faz hoje

### 🟢 Portas

- consulta status da interface;
- mostra VLAN;
- duplex;
- velocidade;
- estado da porta;
- shutdown;
- no shutdown;
- remoção de sticky MAC;
- atualização periódica das portas.

---

### 🔎 Localização de dispositivos

É possível pesquisar um endereço MAC e procurar em vários switches.

A aplicação tenta ignorar links entre switches para mostrar a porta onde o dispositivo realmente está conectado.

Exemplo:

```text
MAC
 ↓
SW01
 ↓ trunk
SW02
 ↓ trunk
SW03
 ↓
Gi1/0/18
