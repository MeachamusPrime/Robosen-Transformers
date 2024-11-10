#!/usr/bin/env python3

# Licensed under the FreeBSD License
# Copyright (c) 2024, Chris Meacham and Terry Meacham
#
# Redistribution and use in source and binary forms, with or without modification, 
# are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this 
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, 
#    this list of conditions and the following disclaimer in the documentation 
#    and/or other materials provided with the distribution.
#
#         THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND 
#         CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, 
#         INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF 
#         MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE 
#         DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR 
#         CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, 
#         SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT 
#         NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; 
#         LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) 
#         HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN 
#         CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR 
#         OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, 
#         EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import sys
sys.coinit_flags = 0  # 0 means MTA (Multi Threaded Apartment) which is needed for bleak
import platform
from typing import Tuple
import time
import argparse
import asyncio
import pygame
if platform.system() == 'Windows':
    import keyboard
from bleak import BleakScanner

from robosen import Platforms, RobotWrapper, IRobotHandler

def split( command: str ):
    start = 0
    while command[start] == ' ' or command[start] == '\t':
        if len(command) > start:
            start = start + 1
        else:
            return None, None
    space = command[start:].find(' ')
    comma = command[start:].find(',')
    start = comma + 1
    if space != -1 and len(command) > space:
        if comma != -1:
            while command[start] == ' ' or command[start] == '\t':
                if len(command) > start:
                    start = start + 1
                else:
                    return [command[0:space], int(command[space+1:comma])], None
            return [command[0:space], int(command[space+1:comma])], command[start:]
        else:
            return [command[0:space], int(command[space+1:])], None
    return None, None

async def list_ble_devices():
    devices = await BleakScanner.discover(timeout = 5.0, return_adv = True )
    for device in devices:
        print(f"Device: {devices[device][0].name}, Address: {devices[device][0].address}, RSSI: {devices[device][1].rssi}")
        print(devices[device][1].service_uuids)

async def list_ble_device_names() -> list:
    devices = await BleakScanner.discover(timeout = 5.0, return_adv = True )
    names = []
    for device in devices:
        name = devices[device][0].name
        if name is None:
            continue
        if name.find("OP-M-") == 0:
            names.append(name)
        elif name.find("GSEG-") == 0:
            names.append(name)
        elif name.find("MEGAF-") == 0:
            names.append(name)
    return names

async def get_first_platform(name: str):
    devices = await BleakScanner.discover(timeout = 5.0)
    for device in devices:
        if device.name is not None:
            result = device.name.find(name)
            if result != -1:
                if name.find("OP-M-") == 0:
                    print(f"Connecting to Optimus Prime: {device.name}\n\tFreedom is the right of all sentient beings...")
                    return [device.address, Platforms.OPTIMUS_PRIME, name[5:]]
                elif name.find("GSEG-") == 0:
                    print(f"Connecting to Grimlock: {device.name}\n\tMe, Grimlock, stronger. Me, Grimlock must lead.")
                    return [device.address, Platforms.GRIMLOCK, name[5:]]
                elif name.find("MEGAF-") == 0:
                    print(f"Connecting to Megatron: {device.name}\n\tPower flows to the one who knows how. Desire alone is not enough.")
                    return [device.address, Platforms.GRIMLOCK, name[5:]]
                    # return [device.address, Platforms.MEGATRON, name[5:]]
    return ["", Platforms.UNKNOWN, "UNKNOWN"]

class TextHandler(IRobotHandler):
    async def run(self):

        robots = []
        while True:
            print("\n")
            await asyncio.sleep(0.02)
            for i, robot in enumerate(robots):
                if not robot.moving() and not robot.acting():
                    await robot.status()
                print(f"Robot {i}: {robot.__str__()}")

            full_command = input(f"Enter command ('discover' to list devices, 'connect <name>' to connect, 'exit' to quit)\n"
                                 f"If a robot is connected, precede the command with the robot number:\n\n")

            if len(full_command) == 0:
                continue

            start = 0
            while full_command[start] == ' ' or full_command[start] == '\t':
                if len(full_command) > start:
                    start = start + 1
                else:
                    continue
            full_command = full_command[start:]

            if full_command.find("exit") == 0:
                break

            if full_command == "discover":
                await list_ble_devices()
                continue

            space = full_command.find(' ')
            if full_command.find("connect") == 0:
                if space == -1:
                    names = await list_ble_device_names()
                    for name in names:
                        found = False
                        for robot in robots:
                            if name == robot.name():
                                found = True
                        if found == False:
                            robot = RobotWrapper()
                            await robot.create_robot(name)
                            if robot.connected():
                                print(f"Robot {name} connected!")
                                robots.append(robot)
                            else:
                                print(f"Robot {name} failed to connect.")
                            continue
                else:
                    command = full_command[space+1:]

                    start = 0
                    while command[start] == ' ' or command[start] == '\t':
                        if len(command) > start:
                            start = start + 1
                        else:
                            continue
                    command = command[start:]

                    robot = RobotWrapper()
                    await robot.create_robot(name)
                    if robot.connected():
                        print(f"Robot {command} connected!")
                        robots.append(robot)
                    else:
                        print(f"Robot {command} failed to connect.")
                continue

            if len(robots) == 0:
                print("Please connect a robot first!")
                continue

            if space == -1 or not full_command[0:space].isnumeric():
                print("No robot was selected, assuming 0!")
                robot_number = int(0)
                command = full_command

                start = 0
                while command[start] == ' ' or command[start] == '\t':
                    if len(command) > start:
                        start = start + 1
                    else:
                        print("No robot was selected or no command was found!")
                        continue
                command = command[start:]
            else:
                robot_number = int(full_command[0:space])
                command = full_command[space+1:]

                start = 0
                while command[start] == ' ' or command[start] == '\t':
                    if len(command) > start:
                        start = start + 1
                    else:
                        continue
                command = command[start:]

            # robot_number is needed from here
            if not (isinstance(robot_number, int)):
                print("Robot designation needs to be a number")
                continue

            if command == "s" or command == "stop":
                await robots[robot_number].stop()
                continue

            if command == "disconnect":
                await robots[robot_number].disconnect()
                connected = robots[robot_number].connected()
                if connected != True:
                    robots.remove(robots[robot_number])
                continue

            if command == "usb":
                await robots[robot_number].enter_usb_mode()
                continue

            if command == "shutdown":
                await robots[robot_number].shutdown()
                await robots[robot_number].disconnect()
                connected = robots[robot_number].connected()
                if connected != True:
                    robots.remove(robots[robot_number])
                continue

            if command == "debug_acting" or command == "da":
                robots[robot_number]._repl_device.state.acting = False
                continue

            if command == "debug_transforming" or command == "dt":
                robots[robot_number]._repl_device.state.acting = False
                continue

            if command == "model":
                await robots[robot_number].model()
                continue

            if command == "version":
                await robots[robot_number].version()
                continue

            if command == "firmware" or command == "fw":
                await robots[robot_number].firmware()
                continue

            if command == "serial":
                await robots[robot_number].serial_number()
                continue

            if command == "transform" or command == "convert":
                await robots[robot_number].transform()
                continue

            if command == "forward" or command == "f":
                await robots[robot_number].forward()
                continue

            if command == "turn-right" or command == "tr":
                await robots[robot_number].turn_right()
                continue

            if command == "horn" or command == "step-right" or command == "sr":
                await robots[robot_number].step_right()
                continue

            if command == "reverse-right" or command == "rr":
                await robots[robot_number].reverse_right()
                continue

            if command == "reverse" or command == "r":
                await robots[robot_number].reverse()
                continue

            if command == "reverse-left" or command == "rl":
                await robots[robot_number].reverse_left()
                continue

            if command == "horn-2" or command == "step-left" or command == "sl":
                await robots[robot_number].step_left()
                continue

            if command == "turn-left" or command == "tl":
                await robots[robot_number].turn_left()
                continue

            if command == "speed":
                await robots[robot_number].change_speed()
                continue

            # Action, CombatAction, RobotAction, Robotdrama, SysAction, CacheLongAction, CacheRobotAction
            if command.find("read") == 0 and len(command) > 5:
                await robots[robot_number].read_directory(command[5:])
                await asyncio.sleep(2)
                continue

            if command.find("exec") == 0 and len(command) > 5:
                await robots[robot_number].execute_file(command[5:])
                continue

            if command == "melee":
                await robots[robot_number].melee()
                continue

            if command == "shoot":
                await robots[robot_number].shoot()
                continue

            if command == "random-action" or command == "truck-quote":
                await robots[robot_number].random_action()
                continue

            if command == "prog_init" or command == "prog_init_robot":
                await robots[robot_number].prog_init(True)
                continue

            if command == "prog_init_dinosaur" or command == "prog_init_vehicle":
                await robots[robot_number].prog_init(False)
                continue

            if command == "prog_exit":
                await robots[robot_number].prog_exit()
                continue

            if command == "unlock-all":
                await robots[robot_number].unlock_all()
                continue

            if command == "lock-all":
                await robots[robot_number].lock_all()
                continue

            if command == "load-position":
                await robots[robot_number].load_position()
                continue

            if command == "robot-default":
                await robots[robot_number].set_position(robots[robot_number].get_position_humanoid())
                continue

            if command.find("lock") != -1 and len(command) > 5:
                commandedState = await robots[robot_number].get_position()
                if command[5:] in commandedState.data:
                    commandedState.data[command[5:]].locked = True
                    await robots[robot_number].set_locks(commandedState)
                continue

            if command.find("unlock") != -1 and len(command) > 7:
                commandedState = await robots[robot_number].get_position()
                if command[7:] in commandedState.data:
                    commandedState.data[command[7:]].locked = False
                    await robots[robot_number].set_locks(commandedState)
                continue

            if robots[robot_number].platform() == Platforms.OPTIMUS_PRIME:
                if command.find("spin") != -1 and len(command) > 5:
                    commandedState = await robots[robot_number].get_position()
                    await robots[robot_number].spin_wheel(command[5:])
                    continue

                if command == "wheels":
                    commandedState = await robots[robot_number].get_position()
                    commandedState.data["leftWheelSpeed"].locked = False
                    commandedState.data["rightWheelSpeed"].locked = False
                    await robots[robot_number].set_locks(commandedState)
                    continue

                if command is not None and command != "":
                    if robots[robot_number].offsets_initialized() == False:
                        print("Offsets not initialized! Run prog_init first!")
                        await robots[robot_number].execute_file("IJustWantHimToComplainHere")
                        continue
                    any_commands = False
                    servo_command, commands = split(command)
                    print(servo_command)
                    if servo_command is not None:
                        commandedState = await robots[robot_number].get_position()
                        any_commands = True
                    while servo_command is not None and len(servo_command) > 1:
                        if servo_command[0] in commandedState.data:
                            commandedState.data[servo_command[0]].value = int(servo_command[1])
                        if commands is None:
                            break
                        servo_command, commands = split(commands)
                        print(servo_command)
                    if any_commands == True:
                        print(commandedState)
                        await robots[robot_number].set_position(commandedState)
                    else:
                        await robots[robot_number].execute_file("IJustWantHimToComplainHere")
                    continue

        for robot in robots:
            await robot.stop()
            await robot.disconnect()

async def get_joysticks() -> list:
    X360Receiver = "Xbox 360 Wireless Receiver for Windows"
    NostromoSpeedPad2 = "Nostromo n52 Speedpad2"
    joysticks = []
    for x in range(pygame.joystick.get_count()):
        name = pygame.joystick.Joystick(x).get_name()
        if name != X360Receiver and name != NostromoSpeedPad2:
            joysticks.append(pygame.joystick.Joystick(x))
    return joysticks

class JoystickHandler(IRobotHandler):
    def __init__(self):
        self.robots = []
        self.last_update = []
        self.PS4 = "PS4 Controller"
        self.X360W = "Controller (XBOX 360 For Windows)"
        self.X360 = "Xbox 360 Controller"
        self.XX = "Xbox Series X Controller"
        self.XS = "Xbox Series S Controller"
        self.JoyConR = "Nintendo Switch Joy-Con (R)"
        self.JoyConL = "Nintendo Switch Joy-Con (L)"
        self.SwitchPro = "Nintendo Switch Pro Controller"
        self.PS5 = "DualSense Wireless Controller"

    async def update_robots(self, joysticks: list):
        print("getting names")
        names = await list_ble_device_names()
        print(f"names: {names}")
        i = 0
        for name in names:
            if len(self.robots) < len(joysticks):
                found = False
                for robot in self.robots:
                    if robot.name() == name:
                        found = True
                if found == False:
                    await asyncio.sleep(0.02)
                    robot = RobotWrapper()
                    await robot.create_robot(name)
                    await asyncio.sleep(0.02)
                    if robot.connected():
                        print( f"Robot {name} connected to joystick {joysticks[i]} (joystick {i})!" )
                        self.robots.append(robot)
                        self.last_update.append(time.time())
                else:
                    print( f"Robot {name} already connected to joystick {joysticks[i]} (joystick {i})..." )
                i = i + 1
        while len(self.robots) > len(joysticks):
            self.robots.remove(self.robots[len(self.robots) - 1])
            self.last_update.remove(self.last_update[len(self.last_update) - 1])

    async def run(self):
        sys.stdout.write("\x1b[2J\x1b[H\n") # Clear screen
        sys.stdout.write("\n\n\n\n\n\n\n\n") # Clear space for status
        pygame.init()
        pygame.joystick.init()
        pygame.event.wait()
        joysticks = await get_joysticks()
        num_joysticks = len(joysticks)
        joystick_names = [joysticks[x].get_name() for x in range(len(joysticks))]
        if num_joysticks == 0:
            print("No controllers present. Exiting.")
            pygame.joystick.quit()
            pygame.quit()
            return

        await asyncio.sleep(0.02)
        # Have to disengage controllers because pygame hijacks the asyncio event loop
        pygame.joystick.quit()
        pygame.quit()

        await self.update_robots(joystick_names)
        if len(self.robots) == 0:
            print("No robots found. Exiting.")
            return
        for robot in self.robots:
            await robot.status()
            
        # Engage controllers
        pygame.init()
        pygame.joystick.init()
        joysticks = await get_joysticks()
        num_joysticks = len(joysticks)
        last_update = 0.0
        updated = False

        while True:
            if (last_update < time.time() - 0.5):
                last_update = time.time()
                sys.stdout.write("\x1b[H")
                print(f"Robots:\n")
                for r, robot in enumerate(self.robots):
                    if not robot.moving() and not robot.acting() and self.last_update[r] < time.time() - 1.0:
                        self.last_update[r] = time.time()
                        await robot.status()
                        updated = True
                    print( f"{robot.__str__()}              " )
                print("\n\n") # Buffer for status
            if updated == True:
                updated = False
            else:
                await asyncio.sleep(0.02)
            pygame.event.wait()

            # Catch the Escape key as a cancel key
            if platform.system() == 'Windows':
                if keyboard.is_pressed('esc'):
                    break

            # Catch input
            first = True
            breakout = False
            for i, joystick in enumerate(joysticks):
                ps4 = False
                x360 = False
                xOne = False
                joyCon = False
                ps5 = False
                switchPro = False 
                if (joystick.get_name() == self.PS4):
                    ps4 = True
                elif ((joystick.get_name() == self.X360) or (joystick.get_name() == self.X360W)):
                    x360 = True
                elif ((joystick.get_name() == self.XX) or (joystick.get_name() == self.XS)):
                    xOne = True
                elif ((joystick.get_name() == self.JoyConR) or (joystick.get_name() == self.JoyConL)):
                    joyCon = True
                elif (joystick.get_name() == self.PS5):
                    ps5 = True
                elif (joystick.get_name() == self.SwitchPro):
                    switchPro = True

                if i >= len(self.robots):
                    break
                if first == True:
                    first = False
                    # Exit controller if touchpad/back/JoyConHomeCapture/ProHome is clicked
                    if ((ps4 or ps5) and joystick.get_button(15)) or \
                       ((x360 or xOne) and joystick.get_button(6)) or \
                       (joyCon and joystick.get_button(5)):
                        breakout = True
                        break
                    # Check for new robots if options/start/JoyCon+-/Pro+ is clicked
                    if ((ps4 or ps5 or joyCon) and \
                        joystick.get_button(6)) or \
                       ((x360 or xOne) and joystick.get_button(7)):
                        for robot in self.robots:
                            robot.stop
                        joysticks = await get_joysticks()
                        num_joysticks = len(joysticks)
                        joystick_names = [joysticks[x].get_name() for x in range(len(joysticks))]
                        # Have to disengage controllers because pygame hijacks the asyncio event loop
                        pygame.joystick.quit()
                        pygame.quit()

                        await self.update_robots(joystick_names)
                        if len(self.robots) == 0:
                            print("No robots found. Exiting.")
                            return
                            
                        # Engage controllers
                        pygame.init()
                        pygame.joystick.init()
                        joysticks = [pygame.joystick.Joystick(x) for x in range(pygame.joystick.get_count())]
                        break
                # Transform if Right/JoyCon Stick is clicked
                if ((ps4 or ps5) and joystick.get_button(8)) or \
                   ((x360 or xOne) and joystick.get_button(9)) or \
                   (joyCon and joystick.get_button(7)):
                    if self.robots[i].moving() == True:
                        await self.robots[i].stop()
                    await self.robots[i].transform()
                    continue
                # 
                # Melee if Triangle/Y/Y is clicked
                elif ((ps4 or ps5 or x360 or xOne) and joystick.get_button(3)) or \
                     (joyCon and joystick.get_button(2)):
                    if self.robots[i].platform() == Platforms.OPTIMUS_PRIME and await self.robots[i].vehicle_mode():
                        await self.robots[i].horn2()
                    else:
                        await self.robots[i].melee()
                    continue
                # Shoot if Square/X/B is clicked
                elif ((ps4 or ps5 or x360 or xOne) and joystick.get_button(2)) or \
                     (joyCon and joystick.get_button(3)):
                    if self.robots[i].platform() == Platforms.OPTIMUS_PRIME and await self.robots[i].vehicle_mode():
                        await self.robots[i].horn1()
                    else:
                        await self.robots[i].shoot()
                    continue
                # Truck Quote or Robot Action if Circle/B/X is clicked
                elif ((ps4 or ps5 or x360 or xOne) and joystick.get_button(1)) or \
                     (joyCon and joystick.get_button(0)):
                    await self.robots[i].random_action()
                    continue
                # X/A/A is speed change
                elif ((ps4 or ps5 or x360 or xOne) and joystick.get_button(0)) or \
                     (joyCon and joystick.get_button(1)):
                    await self.robots[i].change_speed()
                    continue
                # If Right Trigger > 50 forward
                elif ((ps4 or ps5 or x360 or xOne) and joystick.get_axis(5) > 0.5) or \
                     (joyCon and joystick.get_button(10)):
                    # If Axis 0 (left stick horizontal) > 50 or < -50 turn
                    if ((ps4 or ps5 or x360 or joyCon or xOne) and \
                        joystick.get_axis(0) < -0.5):
                        await self.robots[i].turn_left()
                        continue
                    elif ((ps4 or ps5 or x360 or joyCon or xOne) and \
                          joystick.get_axis(0) > 0.5):
                        await self.robots[i].turn_right()
                        continue
                    else:
                        await self.robots[i].forward()
                        if joyCon:
                            await self.robots[i].forward()
                        continue
                # If Left Trigger > 50 reverse
                elif ((ps4 or ps5 or x360 or xOne) and joystick.get_axis(4) > 0.5) or \
                     (joyCon and joystick.get_button(9)):
                    # If Left Stick horizontal > 0.50 or < -0.50 turn
                    if ((ps4 or ps5 or x360 or joyCon or xOne) and \
                        joystick.get_axis(0) < -0.5):
                        await self.robots[i].reverse_left()
                        continue
                    elif ((ps4 or ps5 or x360 or joyCon or xOne) and \
                          joystick.get_axis(0) > 0.5):
                        await self.robots[i].reverse_right()
                        continue
                    else:
                        await self.robots[i].reverse()
                        if joyCon:
                            await self.robots[i].reverse()
                        continue
                # If Left Stick horizontal > 0.50 or < -0.50 step
                elif ((ps4 or ps5 or x360 or joyCon or xOne) and \
                      joystick.get_axis(0) < -0.5):
                    if (await self.robots[i].vehicle_mode() == False or self.robots[i].platform() == Platforms.MEGATRON):
                        await self.robots[i].step_left()
                    continue
                elif ((ps4 or ps5 or x360 or joyCon or xOne) and \
                      joystick.get_axis(0) > 0.5):
                    if (await self.robots[i].vehicle_mode() == False or self.robots[i].platform() == Platforms.MEGATRON):
                        await self.robots[i].step_right()
                    continue
                else:
                    if self.robots[i].moving() == True:
                        await self.robots[i].stop()
                        await self.robots[i].status()
                    continue
            if breakout == True:
                print("Done Playing. Disconnecting now.")
                break

        pygame.joystick.quit()
        pygame.quit()
        for robot in self.robots:
            await robot.stop()
            await robot.disconnect()

class JoystickTester(IRobotHandler):
    async def run(self):
        sys.stdout.write("\x1b[2J\x1b[H\n") # Clear screen
        sys.stdout.write("\n\n\n\n\n\n\n\n") # Clear space for status
        pygame.init()
        pygame.joystick.init()
        pygame.event.wait()
        if pygame.joystick.get_count() == 0:
            print("No controllers present. Exiting.")
            pygame.joystick.quit()
            pygame.quit()
            return

        while True:
            pygame.event.wait()
            sys.stdout.write("\x1b[H") # Reset the cursor
            joysticks = await get_joysticks()
            for joystick in joysticks:
                print(joystick.get_name())
                for button in range(0, joystick.get_numbuttons()):
                    print(f"button {button}: {joystick.get_button(button)}")
                for axis in range(0, joystick.get_numaxes()):
                    print(f"axis {axis}: {joystick.get_axis(axis)}")

            if platform.system() == 'Windows':
                if keyboard.is_pressed('esc'):
                    print("Exiting.")
                    pygame.joystick.quit()
                    pygame.quit()
                    return

def main():
    parser = argparse.ArgumentParser(description="Bluetooth LE REPL")
    parser.add_argument("--test_joysticks", action="store_true", help="Display information for connected joysticks")
    parser.add_argument("--joystick", action="store_true", help="Connect to Transformer(s) in joystick mode")
    parser.add_argument("--discover", action="store_true", help="Discover BLE devices")
    parser.add_argument("--text", action="store_true", help="Connect to Transformer(s) in text mode")

    args = parser.parse_args()

    if args.discover:
        asyncio.run(list_ble_devices())

    elif args.text:
        # Call Text Interface Handler
        handler = TextHandler()
        asyncio.run(handler.run())

    elif args.joystick:
        # Call Joystick Handler
        handler = JoystickHandler()
        asyncio.run(handler.run())

    elif args.test_joysticks:
        # Call Joystick Tester
        handler = JoystickTester()
        asyncio.run(handler.run())

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
