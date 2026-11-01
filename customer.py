from socket import *
import json

serverName = 'localhost'
serverPort = 12000
clientSocket = socket(AF_INET, SOCK_DGRAM)
serverAddress = (serverName, serverPort)

login = False

while not login:
    user_id = input('Input username: ')
    password = input('Input password: ')

    payload = json.dumps({
        "id": user_id,
        "password": password
    })

    clientSocket.sendto(payload.encode("utf-8"),serverAddress)


    response, _  = clientSocket.recvfrom(2048)
    response = response.decode("utf-8")


    if response == "passVerified":
        login = True
    else:
        print("Login Failed")

print ("Login Successful")

text = "ack"
payload = json.dumps({
    "text": text
})
clientSocket.sendto(payload.encode("utf-8"), serverAddress)

while True:
    response, _ = clientSocket.recvfrom(2048)
    print(response.decode("utf-8"))
    if response == "kill":
        break

    text = input('YES if you want to proceed: ')
    payload = json.dumps({
        "text": text
    })
    clientSocket.sendto(payload.encode("utf-8"), serverAddress)

