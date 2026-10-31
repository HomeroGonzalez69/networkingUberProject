from http import client
from socket import *
import json

#opens and loads the JSON file safely while using a context manager
with open("uberProject.json", "r", encoding="utf-8") as file:
    data = json.load(file)


serverPort = 12000
serverSocket = socket(AF_INET, SOCK_DGRAM)
serverSocket.bind(('', serverPort))
print ('The server is ready to receive')
signedIn = 0
while signedIn != 2:
    message, clientAddress = serverSocket.recvfrom(2048)
    message = message.decode()
    #modifiedMessage = message.decode().upper()
    #serverSocket.sendto(modifiedMessage.encode(), clientAddress)
    if message[0] == 'A' or message[0] == 'B' or message[0] == 'C' or message[0] == 'D' or message[0] == 'E' or message[0] == 'F':
        passwordCheck = message[1:]
        for customer in data["Customer"]:
            if customer["id"] == message[0]:
                if customer["password"] == passwordCheck:
                    returnMessage = "passVerified"
                    serverSocket.sendto(returnMessage.encode(), clientAddress)
                    customerAdd = tuple(clientAddress)
                    signedIn+=1
                    message = " "
                else:
                    returnMessage = "Invalid User"
                    serverSocket.sendto(returnMessage.encode(), clientAddress)
        for driver in data["Driver"]:
            if driver["id"] == message[0]:
                if driver["password"] == passwordCheck:
                    returnMessage = "passVerified"
                    serverSocket.sendto(returnMessage.encode(), clientAddress)
                    driverAdd = tuple(clientAddress)
                    signedIn+=1
                    message = " "
                else:
                    returnMessage = "Invalid User"
                    serverSocket.sendto(returnMessage.encode(), clientAddress)
    else:
        returnMessage = "Invalid User"
        serverSocket.sendto(returnMessage.encode(), clientAddress)

customerMessage = "customer"
print(customerAdd)
serverSocket.sendto(customerMessage.encode(), customerAdd)

driverMessage = "driver"
print(driverAdd)
serverSocket.sendto(driverMessage.encode(), driverAdd)


