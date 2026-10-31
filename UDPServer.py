from http import client
from socket import *
import json

#opens and loads the JSON file safely while using a context manager
with open("uberProject.json", "r+", encoding="utf-8") as file:
    data = json.load(file)

    
def passwordCheck(user_id, password):
    user_id = str(user_id).strip()

    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            if str(person.get("id")) == user_id:
                if person.get("password") == password:
                    return group.lower()
                return "invalid" # ID exist, but wrong password
    return "invalid"


def serverCheck(data, address):
    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            savedAddress = person.get("serverAddress")
            if savedAddress and tuple(savedAddress) == address:
                print(f"Found {group} at address: {address}")
                return group
    print(f"Address {address} not found")
    return "Unknown"


def addFinder(id):
    address = ()
    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            if str(person.get("id")) == str(id):
                address = person.get("serverAddress")
                break
            else:
                continue
        break
    if address == ():
        print(f"ID {id} not found")
    return tuple(address)


def writeJSON():
    with open("uberProject.json", "w", encoding="utf-8") as file:
        file.seek(0)
        json.dump(data, file, indent=2)
        file.truncate()
        file.seek(0)
        return True
    



serverPort = 12000
serverSocket = socket(AF_INET, SOCK_DGRAM)
serverSocket.bind(('', serverPort))
print ('The server is ready to receive')
signedIn = 0
customerAdd = None
driverAdd = None


while True:
    message, clientAddress = serverSocket.recvfrom(2048)
    request = json.loads(message.decode("utf-8"))

    serverChecked = serverCheck(data, clientAddress)

    if serverChecked == "Unknown":
        clientID = str(request["id"])
        clientPass = str(request["password"])

        while True:
            passReturn = passwordCheck(clientID, clientPass)
            if passReturn != "invalid":
                break
            returnMessage = "Invalid User"
            serverSocket.sendto(returnMessage.encode(), clientAddress)

            message, clientAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            clientID = str(request["id"])
            clientPass = str(request["password"])


        if passReturn == "customer":
            returnMessage = "passVerified"
            serverSocket.sendto(returnMessage.encode(), clientAddress)
            for customer in data["Customer"]:
                if customer["id"] == clientID:
                    customer["serverAddress"] = list(clientAddress)
                    break
            writeJSON()

        elif passReturn == "driver":
            returnMessage = "passVerified"
            serverSocket.sendto(returnMessage.encode(), clientAddress)
            for driver in data["Driver"]:
                if driver["id"] == clientID:
                    driver["serverAddress"] = list(clientAddress)
                    break
            writeJSON()
    elif serverChecked == "Driver":
        print("driver server check")

        text = str(request["text"])

        customerMessage = f"driver: {text}"
        serverSocket.sendto(customerMessage.encode(), clientAddress)
    elif serverChecked == "Customer":
        print("customer server check")
        
        text = str(request["text"])

        customerMessage = f"customer: {text}"
        serverSocket.sendto(customerMessage.encode(), clientAddress)