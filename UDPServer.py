from http import client
from socket import *
import json


global data

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


def addressFinder(id):
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

def idFinder(address):
    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            if tuple(person.get("serverAddress")) == address:
                return person.get("id")
    return None

def writeJSON():
    with open("uberProject.json", "r+", encoding="utf-8") as file:
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
        driverMessage = "Would you like to upload a driver headshot?: "
        serverSocket.sendto(driverMessage.encode(), clientAddress)

  
        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])

        if text.lower() == "yes":
            driverMessage = "Please upload your driver headshot."
            serverSocket.sendto(driverMessage.encode(), clientAddress)

            message, clientAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            text = str(request["text"])

            for driver in data["Driver"]:
                if tuple(driver.get("serverAddress", [])) == tuple(clientAddress):
                    driver["headshot"] = list(text)
                    writeJSON()
                    break
            

        driverMessage = "Would you like to see a list your previous rides?"
        serverSocket.sendto(driverMessage.encode(), clientAddress)

        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        rides = ""

        if text.lower() == "yes":
            id = idFinder(tuple(clientAddress))
            for driver in data["rideInfo"]:
                if str(driver["driverId"]) == id:
                    rides += f"Ride ID: {driver['id']}, Customer ID: {driver['customerId']}, Driver ID: {driver['driverId']}, Pickup: {driver['pickupZone']}, Dropoff: {driver['dropoffZone']}, Cost: {driver['cost']}, Request Time: {driver['requestTime']}, Pickup Time: {driver['pickupTime']}, Dropoff Time: {driver['dropoffTime']}\n"

            driverMessage = "Here is a list of your previous rides.\n" + rides + "\nWould you like to request another ride?"
            serverSocket.sendto(driverMessage.encode(), clientAddress)
        else:
            driverMessage = "Would you like to accept a ride?"
            serverSocket.sendto(driverMessage.encode(), clientAddress)

        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])

        if text.lower() == "yes":
            customerMessage = ""
            serverSocket.sendto(customerMessage.encode(), clientAddress)
        else:
            customerMessage = "kill"
            serverSocket.sendto(customerMessage.encode(), clientAddress)
        




    elif serverChecked == "Customer":
        customerMessage = "Would you like to upload a customer headshot?: "
        serverSocket.sendto(customerMessage.encode(), clientAddress)

  
        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])

        if text.lower() == "yes":
            customerMessage = "Please upload your headshot."
            serverSocket.sendto(customerMessage.encode(), clientAddress)

            message, clientAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            text = str(request["text"])

            for customer in data["Customer"]:
                if tuple(customer.get("serverAddress", [])) == tuple(clientAddress):
                    customer["headshot"] = text
                    writeJSON()
                    break
            

        customerMessage = "Would you like to see a list your previous rides?"
        serverSocket.sendto(customerMessage.encode(), clientAddress)

        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        rides = ""

        if text.lower() == "yes":
            id = idFinder(tuple(clientAddress))
            for customer in data["rideInfo"]:
                if str(customer["customerId"]) == id:
                    rides += f"Ride ID: {customer['id']}, Customer ID: {customer['customerId']}, Driver ID: {customer['driverId']}, Pickup: {customer['pickupZone']}, Dropoff: {customer['dropoffZone']}, Cost: {customer['cost']}, Request Time: {customer['requestTime']}, Pickup Time: {customer['pickupTime']}, Dropoff Time: {customer['dropoffTime']}\n"

            customerMessage = "Here is a list of your previous rides.\n" + rides + "\nWould you like to request another ride?"
            serverSocket.sendto(customerMessage.encode(), clientAddress)
        else:
            customerMessage = "Would you like to request another ride?"
            serverSocket.sendto(customerMessage.encode(), clientAddress)

        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])

        if text.lower() == "yes":
            customerMessage = "What is your desired pickup zone?"
            serverSocket.sendto(customerMessage.encode(), clientAddress)
        else:
            customerMessage = "kill"
            serverSocket.sendto(customerMessage.encode(), clientAddress)
