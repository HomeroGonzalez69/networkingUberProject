from http import client
import random
from socket import *
import json
from datetime import datetime
import threading
import queue
import time
import base64
import os

clientQueue = {}
queueLock = threading.Lock()
dataLock = threading.RLock()

global data
random.seed(42)  # Set a fixed seed for reproducibility

# sets up the UDP server socket and listens for incoming messages
serverPort = 12000
serverSocket = socket(AF_INET, SOCK_DGRAM)
serverSocket.bind(('', serverPort))
print('The server is ready to receive')
signedIn = 0
customerAdd = None
driverAdd = None

# opens and loads the JSON file safely while using a context manager
with open("uberProject.json", "r+", encoding="utf-8") as file:
    data = json.load(file)


def recieveFor(address):
    # waits for the next packet routed to this client
    packet = clientQueue[address].get()
    return json.loads(packet.decode("utf-8"))


def sendTo(address, message):
    serverSocket.sendto(message.encode("utf-8"), address)


# Returns the saved file name, or None if no file was received.
def saveHeadshot(userID, request):
    fileName = str(request.get("headshot", ""))
    encoded = str(request.get("data", ""))
    if encoded == "":
        return None
    extension = os.path.splitext(fileName)[1].lower()
    if extension not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        extension = ".jpg"
    savedName = f"{userID}{extension}"
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), savedName), "wb") as imageFile:
            imageFile.write(base64.b64decode(encoded))
    except (ValueError, OSError):
        return None
    return savedName


# builds text tables for the ride lists and the driver info
def makeTable(headers, rows):
    rows = [[str(cell) for cell in row] for row in rows]
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def formatRow(cells):
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"

    return "\n".join([line, formatRow(headers), line] + [formatRow(r) for r in rows] + [line])


statusNames = {1: "1-Requested", 2: "2-Accepted", 3: "3-Picked up", 4: "4-Dropped off"}


# one table row per ride with all the ride request fields (times are shown as HH:MM:SS, Miles = Cost / $5)
def rideTable(rideList, emptyText="(no rides)"):
    if not rideList:
        return emptyText
    headers = ["ID", "Customer", "Driver", "From", "To", "Miles", "Cost", "Requested", "Picked up", "Dropped off",
               "Status"]
    rows = []
    for r in rideList:
        rows.append([r["id"], r["customerId"], r["driverId"] or "-", r["pickupZone"], r["dropoffZone"],
                     round(r["cost"] / 5, 1), f"${r['cost']:.2f}",
                     (r["requestTime"] or "-")[-8:], (r["pickupTime"] or "-")[-8:], (r["dropoffTime"] or "-")[-8:],
                     statusNames[r["pending"]]])
    return makeTable(headers, rows) + "\nFrom/To = pickup/dropoff zone"


def getDistance(zone1, zone2):
    # calculates the distance between two zones based on their coordinates in the JSON data
    zone1_coords = None
    zone2_coords = None

    for zone in data["zones"]:
        if str(zone["zoneId"]) == str(zone1):
            zone1_coords = (zone["zoneLocation"][0], zone["zoneLocation"][1])
        if str(zone["zoneId"]) == str(zone2):
            zone2_coords = (zone["zoneLocation"][0], zone["zoneLocation"][1])

    if zone1_coords is None or zone2_coords is None:
        return None

    distance = ((zone2_coords[0] - zone1_coords[0]) ** 2 + (zone2_coords[1] - zone1_coords[1]) ** 2) ** 0.5
    return round(distance, 1)


# checks if the provided user_id and password match any entry in the JSON data
def passwordCheck(user_id, password, tag):
    user_id = str(user_id).strip()

    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            if str(person.get("id")) == user_id:
                if person.get("password") == password and tag == group.lower():
                    return group.lower()
                return "invalid"  # ID exist, but wrong password
    return "invalid"


# checks if the provided address matches any entry in the JSON data and returns the corresponding group
def serverCheck(data, address):
    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            savedAddress = person.get("serverAddress")
            if savedAddress and tuple(savedAddress) == address:
                print(f"Found {group} at address: {address}")
                return group
    print(f"Address {address} not found")
    return "Unknown"


# takes an ID and returns the corresponding server address from the JSON data
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


# takes an address and returns the corresponding ID from the JSON data
def idFinder(address):
    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            if tuple(person.get("serverAddress")) == address:
                return person.get("id")
    return None


# writes the current state of the JSON data back to the file
def writeJSON():
    with dataLock:
        with open("uberProject.json", "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
    return True


def handleClient(clientAddress):
    try:
        for i in range(2):
            # sets up the server to receive a message from a client and decodes it from JSON format
            request = recieveFor(clientAddress)

            serverChecked = serverCheck(data, clientAddress)

            # if the server address is not recognized, it checks the provided user ID and password against the JSON data
            if serverChecked == "Unknown":
                print(f"Received message from unknown address: {clientAddress}")
                clientID = str(request["id"])
                clientPass = str(request["password"])
                tag = str(request["tag"])

                # loops until a valid user ID and password combination is provided, sending an "Invalid User" message back to the client if the credentials are incorrect
                while True:
                    passReturn = passwordCheck(clientID, clientPass, tag)
                    if passReturn != "invalid":
                        break
                    returnMessage = "Invalid User"

                    print(f"Invalid login attempt from address: {clientAddress} with ID: {clientID}")
                    sendTo(clientAddress, returnMessage)

                    request = recieveFor(clientAddress)
                    clientID = str(request["id"])
                    clientPass = str(request["password"])
                    print(f"Received message from {clientAddress} with ID: {clientID}")

                # if the credentials are valid, it sends a "passVerified" message back to the client and updates the JSON data with the client's server address
                if passReturn == "customer":
                    returnMessage = "passVerified"
                    print(f"Verified login for customer ID: {clientID} from address: {clientAddress}")
                    sendTo(clientAddress, returnMessage)
                    with dataLock:
                        for customer in data["Customer"]:
                            if customer["id"] == clientID:
                                customer["serverAddress"] = list(clientAddress)
                                break
                        writeJSON()

                elif passReturn == "driver":
                    returnMessage = "passVerified"
                    print(f"Verified login for driver ID: {clientID} from address: {clientAddress}")
                    sendTo(clientAddress, returnMessage)
                    with dataLock:
                        for driver in data["Driver"]:
                            if driver["id"] == clientID:
                                driver["serverAddress"] = list(clientAddress)
                                break
                        writeJSON()


            # if the server address is recognized as a driver, it prompts the driver to upload a headshot and view their previous rides, updating the JSON data accordingly.
            #  If the server address is recognized as a customer, it prompts the customer to upload a headshot and view their previous rides, also updating the JSON data accordingly.
            elif serverChecked == "Driver":
                print(f"Received message from Driver address: {clientAddress}")
                driverID = idFinder(tuple(clientAddress))
                driverMessage = "Would you like to upload a driver headshot?: "
                driverAddress = tuple(clientAddress)
                sendTo(driverAddress, driverMessage)
                print(f"Driver ID: {driverID} at address: {driverAddress}. Asking about headshot upload.")

                # receives the driver's response and decodes it from JSON format
                request = recieveFor(driverAddress)
                text = str(request["text"])
                print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")

                # if the driver chooses to upload a headshot, it prompts for the headshot and updates the JSON data with the provided information
                if text.lower() == "yes":
                    driverMessage = "Please upload your driver headshot."
                    sendTo(driverAddress, driverMessage)
                    print(f"Driver ID: {driverID} at address: {driverAddress}. Sent request for headshot upload.")

                    request = recieveFor(driverAddress)
                    filePath = saveHeadshot(driverID, request)
                    print(
                        f"Driver ID: {driverID} at address: {driverAddress} responded to headshot request with: {filePath}")

                    with dataLock:
                        for driver in data["Driver"]:
                            if driverID == driver["id"]:
                                if filePath is not None:
                                    driver["headshot"] = filePath
                                    writeJSON()
                                break

                # prompts the driver to view their previous rides and updates the JSON data accordingly
                driverMessage = "Would you like to see a list your previous rides?"
                sendTo(driverAddress, driverMessage)
                print(f"Driver ID: {driverID} at address: {driverAddress}. Asking about previous rides.")

                request = recieveFor(driverAddress)
                text = str(request["text"])
                print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")
                rides = ""
                print(f"Driver ID: {driverID} at address: {driverAddress}. Responded with: {text}")

                # if the driver chooses to view their previous rides, it retrieves the relevant information from the JSON data and sends it back to the driver.
                # If the driver chooses not to view their previous rides, it prompts them to accept a ride.
                if text.lower() == "yes":
                    # show a table
                    rides = rideTable([r for r in data["rideInfo"] if str(r["driverId"]) == driverID])
                    # next question is now "see requested rides?"
                    driverMessage = "Here is a list of your previous drives.\n" + rides + "\nWould you like to see a list of requested rides?"
                    sendTo(driverAddress, driverMessage)
                else:
                    driverMessage = "Would you like to see a list of requested rides?"
                    sendTo(driverAddress, driverMessage)

                # receives the driver's response and decodes it from JSON format
                request = recieveFor(driverAddress)
                text = str(request["text"])
                print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")

                # Based on the driver's response, it either prompts for the current zone and enters
                # a loop to continuously check for pending ride requests, assigning the first
                # available ride to the driver and updating the JSON data accordingly, or it sends
                # a "kill" message to terminate the interaction.
                if text.lower() == "yes":
                    # send the requested rides (status 1) and let the driver pick one by ride ID
                    chosenRide = None
                    notice = ""
                    while chosenRide is None:
                        with dataLock:
                            requested = [r for r in data["rideInfo"] if r["pending"] == 1]
                        requestedText = rideTable(requested, "(no requested rides right now)")
                        driverMessage = notice + "Here is a list of requested rides.\n" + requestedText + "\nEnter the ride ID to accept (R to refresh, Q to quit):"
                        sendTo(driverAddress, driverMessage)
                        print(
                            f"Driver ID: {driverID} at address: {driverAddress}. Sent the list of requested rides ({len(requested)}).")
                        notice = ""

                        request = recieveFor(driverAddress)
                        choice = str(request["rideId"]).strip().lower()
                        print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {choice}")

                        if choice == "q":
                            break
                        if choice == "r":
                            continue
                        for r in requested:
                            if str(r["id"]) == choice:
                                chosenRide = r
                                break
                        if chosenRide is None:
                            notice = "That ride ID is not in the list.\n"

                    if chosenRide is None:
                        driverMessage = "kill"
                        sendTo(driverAddress, driverMessage)
                        return
                    driverMessage = "What is your current zone? (1, 2, ..., 9)"
                    sendTo(driverAddress, driverMessage)
                    print(f"Driver ID: {driverID} at address: {driverAddress}. Asked for current zone.")

                    # receives the driver's response and decodes it from JSON format
                    request = recieveFor(driverAddress)
                    currentZone = str(request["currentZone"])
                    print(
                        f"Driver ID: {driverID} at address: {driverAddress} responded with current zone: {currentZone}")

                    with dataLock:
                        for driver in data["Driver"]:
                            if driverID == driver["id"]:
                                driver["currentZone"] = currentZone
                                driverCurrentZone = int(currentZone)
                                writeJSON()
                                break

                    # assign the ride the driver CHOSE (was: a loop that grabbed the first pending ride)
                    with dataLock:
                        rideStillFree = chosenRide["pending"] == 1
                        if rideStillFree:
                            chosenRide["pending"] = 2
                            chosenRide["driverId"] = driverID
                            writeJSON()
                    if not rideStillFree:
                        driverMessage = f"Sorry, ride {chosenRide['id']} was just accepted by another driver."
                        sendTo(driverAddress, driverMessage)
                        driverMessage = "kill"
                        sendTo(driverAddress, driverMessage)
                        return
                    print(f"Driver {driverID} accepted ride {chosenRide['id']}.")

                    print("Ride request found. Sending ride details to driver...")
                    request = recieveFor(driverAddress)
                    text = str(request["text"])
                    print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")

                    # the DRIVER confirms pickup and dropoff (was: the server simulated the drive with sleep loops)
                    ride = chosenRide
                    customerID = ride["customerId"]
                    customerAddress = addressFinder(customerID)
                    print(
                        f"Driver {driverID} is heading to pickup zone {ride['pickupZone']} for customer {customerID}.")

                    # the "Ride request accepted ... Have you reached the pickup zone? (YES)" message was sent to the driver
                    # above and the driver's answer to it is in text. Ask again until the answer is yes.
                    while text.lower() != "yes":
                        driverMessage = "Have you reached the pickup zone? (YES)"
                        sendTo(driverAddress, driverMessage)
                        request = recieveFor(driverAddress)
                        text = str(request["text"])
                        print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")

                    with dataLock:
                        ride["pickupTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ride["pending"] = 3
                        for customer in data["Customer"]:
                            if customer["id"] == customerID:
                                customer["riding"] = True
                                break
                        for driver in data["Driver"]:
                            if driver["id"] == driverID:
                                driver["currentZone"] = ride["pickupZone"]
                                break
                        writeJSON()
                    print(f"Driver {driverID} picked up customer {customerID} at pickup zone {ride['pickupZone']}.")

                    print(
                        f"Driver {driverID} is heading to dropoff zone {ride['dropoffZone']} with customer {customerID}.")
                    text = ""
                    while text.lower() != "yes":
                        driverMessage = f"Customer {customerID} picked up. You are on the way to dropoff zone {ride['dropoffZone']}.\nHave you reached the dropoff zone? (YES)"
                        sendTo(driverAddress, driverMessage)
                        request = recieveFor(driverAddress)
                        text = str(request["text"])
                        print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")

                    with dataLock:
                        ride["dropoffTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ride["pending"] = 4
                        for customer in data["Customer"]:
                            if customer["id"] == customerID:
                                customer["riding"] = False
                                customer["currentZone"] = ride["dropoffZone"]
                                break
                        for driver in data["Driver"]:
                            if driver["id"] == driverID:
                                driver["currentZone"] = ride["dropoffZone"]
                                break
                        writeJSON()
                    print(
                        f"Driver {driverID} dropped off customer {customerID} at dropoff zone {ride['dropoffZone']}. Ride {ride['id']} is done.")

                    driverMessage = f"You dropped off customer {customerID} at zone {ride['dropoffZone']}. Ride {ride['id']} is done."
                    sendTo(driverAddress, driverMessage)

                    with dataLock:
                        for driver in data["Driver"]:
                            if driver["id"] == driverID:
                                driver["available"] = True
                                break
                        for customer in data["Customer"]:
                            if customer["id"] == customerID:
                                customer["riding"] = False
                                break
                        writeJSON()

                    driverMessage = "kill"
                    sendTo(driverAddress, driverMessage)
                else:
                    driverMessage = "kill"
                    sendTo(driverAddress, driverMessage)


            # if the server address is recognized as a customer, it prompts the customer to upload a headshot and view their previous rides, updating the JSON data accordingly.
            # If the customer chooses to request another ride, it prompts for the desired pickup zone.
            elif serverChecked == "Customer":
                print(f"Received message from Customer address: {clientAddress}")
                customerMessage = "Would you like to upload a customer headshot?: "
                customerAddress = tuple(clientAddress)
                customerID = idFinder(tuple(customerAddress))
                sendTo(customerAddress, customerMessage)
                print(f"Customer ID: {customerID} at address: {customerAddress}. Asking about headshot upload.")

                # receives the customer's response and decodes it from JSON format
                request = recieveFor(customerAddress)
                text = str(request["text"])
                print(f"Customer ID: {customerID} at address: {customerAddress} responsed with: {text}")

                # if the customer chooses to upload a headshot, it prompts for the headshot and updates the JSON data with the provided information
                if text.lower() == "yes":
                    customerMessage = "Please upload your headshot."
                    sendTo(customerAddress, customerMessage)
                    print(f"Customer ID: {customerID} at address: {customerAddress}. Sent request for headshot upload.")

                    request = recieveFor(customerAddress)
                    filePathHead = saveHeadshot(customerID, request)
                    print(f"Customer ID: {customerID} at address: {customerAddress}. Headshot: {filePathHead}")
                    with dataLock:
                        for customer in data["Customer"]:
                            if tuple(customer.get("serverAddress", [])) == tuple(customerAddress):
                                if filePathHead is not None:
                                    customer["headshot"] = filePathHead
                                writeJSON()
                                break

                # prompts the customer to view their previous rides and updates the JSON data accordingly
                customerMessage = "Would you like to see a list your previous rides?"
                sendTo(customerAddress, customerMessage)
                print(f"Customer ID: {customerID} at address: {customerAddress}. Asking about previous rides.")

                request = recieveFor(customerAddress)
                text = str(request["text"])
                rides = ""
                print(f"Customer ID: {customerID} at address: {customerAddress}. Responded with: {text}")

                # if the customer chooses to view their previous rides, it retrieves the relevant information from the
                # JSON data and sends it back to the customer. If the customer chooses not to view their previous
                #  rides, it prompts them to request another ride.
                if text.lower() == "yes":
                    rides = rideTable([r for r in data["rideInfo"] if str(r["customerId"]) == customerID])
                    customerMessage = "Here is a list of your previous rides.\n" + rides + "\nWould you like to request another ride?"
                    sendTo(customerAddress, customerMessage)
                    print(
                        f"Customer ID: {customerID} at address: {customerAddress}. Sent previous rides and asked about requesting another ride.")
                else:
                    customerMessage = "Would you like to request another ride?"
                    sendTo(customerAddress, customerMessage)
                    print(
                        f"Customer ID: {customerID} at address: {customerAddress}. Asked about requesting another ride.")

                # receives the customer's response and decodes it from JSON format
                request = recieveFor(customerAddress)
                text = str(request["text"])
                print(f"Customer ID: {customerID} at address: {customerAddress}. Responded with: {text}")

                # Based on the customer's response, it either prompts for the desired pickup and dropoff zones and
                # updates the JSON data with the ride request information, or it sends a "kill" message to
                # terminate the interaction.
                if text.lower() == "yes":
                    customerMessage = "What is your desired pickup and dropoff zone? EX: Pickup zone: 1, Dropoff zone: 2"
                    sendTo(customerAddress, customerMessage)
                    print(
                        f"Customer ID: {customerID} at address: {customerAddress}. Asked for pickup and dropoff zones.")

                    request = recieveFor(customerAddress)
                    pickup_zone = str(request["pickupZone"])
                    dropoff_zone = str(request["dropoffZone"])

                    print(
                        f"Customer ID: {customerID} at address: {customerAddress}. Pickup zone: {pickup_zone}, Dropoff zone: {dropoff_zone}")

                    with dataLock:
                        for customer in data["Customer"]:
                            if tuple(customer.get("serverAddress", [])) == tuple(customerAddress):
                                customer["currentZone"] = pickup_zone
                                writeJSON()
                                break

                    customerMessage = "Your ride request has been sent to available drivers."
                    sendTo(customerAddress, customerMessage)
                    driverFound = False
                    print("Waiting for a driver to accept the ride request...")
                    # Collects the customer's ID, pickup zone, dropoff zone, request time, and calculates the
                    # cost of the ride based on the distance between the pickup and dropoff zones.
                    # It then updates the JSON data with this information and sends a message to the customer
                    # confirming that their ride request has been sent to available drivers. The server then
                    #  enters a loop to wait for a response from a driver, and if a driver accepts the ride request,
                    # it updates the JSON data
                    with dataLock:
                        rideNumber = max([r["id"] for r in data["rideInfo"]], default=0) + 1
                        ride = {
                            "pending": 1,
                            "id": rideNumber,
                            "driverId": None,
                            "customerId": customerID,
                            "pickupZone": pickup_zone,
                            "dropoffZone": dropoff_zone,
                            "requestTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "pickupTime": None,
                            "dropoffTime": None,
                            "cost": getDistance(pickup_zone, dropoff_zone) * 5
                        }

                        data["rideInfo"].append(ride)
                        writeJSON()
                    #  wait for THIS customer's own ride
                    while not driverFound:
                        time.sleep(1)
                        if ride["pending"] >= 2:
                            driverFound = True
                            ride_id = ride["id"]
                            driver_id = ride["driverId"]

                    with dataLock:
                        for driver in data["Driver"]:
                            if driver["id"] == driver_id:
                                driverTable = makeTable(
                                    ["Driver", "Current zone", "Car model", "Car color", "Plate number", "Headshot",
                                     "Availability"],
                                    [[driver_id, driver["currentZone"], driver["model"], driver["color"],
                                      driver["plateNumber"], driver["headshot"] or "-", "Busy"]])
                                customerMessage = f"\nRide {ride_id} initiated\nDriver {driver_id} has accepted your ride request.\n" + driverTable
                                driver["available"] = False
                                break

                        writeJSON()

                    sendTo(customerAddress, customerMessage)
                    driverMessage = f"Ride request accepted. \nCustomer ID: {customerID}, \nPickup Zone: {pickup_zone}, \nDropoff Zone: {dropoff_zone}, \nCost: {ride['cost']}"
                    driverMessage += "\nYou are on the way to the pickup zone.\nHave you reached the pickup zone? (YES)"
                    for driver in data["Driver"]:
                        if driver["id"] == driver_id:
                            driverAddress = tuple(driver.get("serverAddress", []))
                            break

                    print(f"Sent ride request details.")
                    sendTo(driverAddress, driverMessage)

                    customerMessage = "kill"
                    sendTo(customerAddress, customerMessage)

                else:
                    customerMessage = "kill"
                    sendTo(customerAddress, customerMessage)

    except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as error:
        print(f"Invalid Packet from {clientAddress}: {error}")
    finally:
        with queueLock:
            clientQueue.pop(clientAddress, None)


while True:
    packet, clientAddress = serverSocket.recvfrom(65535)

    with queueLock:
        packetQueue = clientQueue.get(clientAddress)

        if packetQueue is None:
            packetQueue = queue.Queue()
            clientQueue[clientAddress] = packetQueue
            packetQueue.put(packet)

            threading.Thread(target=handleClient, args=(clientAddress,), daemon=True, ).start()
        else:
            packetQueue.put(packet)
