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

import traceback
import re, itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import asyncio
import time
from bleak import BleakClient, BleakScanner
from pydantic import BaseModel

from robot_states import RobotState, Optimus, Grimlock, Megatron

UUID_WRITE = "0000ffe1-0000-1000-8000-00805f9b34fb"
UUID_NOTIFY = "0000ffe1-0000-1000-8000-00805f9b34fb"

class Commands(Enum):
    FORWARD = 1
    TURN_RIGHT = 2
    STEP_RIGHT = 3
    REVERSE_RIGHT = 4
    REVERSE = 5
    REVERSE_LEFT = 6
    STEP_LEFT = 7
    TURN_LEFT = 8
    BUILT_IN_ACTION = 9 # Built in Robot Action? 
            # Has a number for data byte (Witnessed Optimus 7[Autobot], 5[Shoot], 4[Axe],)
            # Returns ACTION_PROGRESS multiple times with the current percentage complete from 0-100
            # Returns ACTION_COMPLETE immediately after ACTION_PROGRESS returns 100
    TRANSFORM = 10 # This command requires a data byte of 00 and 
                   # receives an immediate response and a finished response
    ACTION_COMPLETE = 11 # Response Action Complete
    STOP = 12 # Ends the Action in progress
    GET_STATE = 15
    ACTION_PROGRESS = 17 # Response Action Progress with the current percentage complete from 0-100
    READ_DIRECTORY = 22 # Reads the attached folder name in the root directory
    EXECUTE_FILE = 23 # Command Attachment: <Folder name>/<Action name without ".sh">
                      # Returns EXECUTE_FILE multiple times with the current percentage complete from 0-100
                      # Returns ACTION_COMPLETE immediately after EXECUTE_FILE returns 100
    CREATE_FILE = 220
    UNLINK = 221
    READ_FILE = 222
    FILE_EXISTS = 225
    WRITE_FILE = 227
    ENTER_BLUETOOTH_PROGRAMMING_MODE = 230
    EXIT_BLUETOOTH_PROGRAMMING_MODE = 231
    SET_POSITION = 232
    GET_POSITION = 233
    UNLOCK_ALL = 234
    LOCK_ALL = 235
    LOCK = 236
    LOCKS = 237
    SERIAL_NUMBER = 241
    ENTER_USB_MODE = 245
    MODEL = 246
    VERSION = 247
    FIRMWARE_DATE = 248
    SHUTDOWN = 250

class Platforms(Enum):
    UNKNOWN = 0
    OPTIMUS_PRIME = 1
    GRIMLOCK = 2
    MEGATRON = 3

class BluetoothDevice(BaseModel):
    address: str
    write_uuid: str
    notify_uuid: str
    platform: Platforms
    id: str

@dataclass
class Command:
    command: Commands | None = None
    data: list[int] = field(default_factory=list)

    @classmethod
    def calc_checksum(cls, data):
        return sum(data) % 256

    def to_byte_list(self, header=True):
        header_data = [255, 255] if header else []
        data = [
            len(self.data) + 2,
            self.command.value,
            *self.data
        ]
        return header_data + data + [self.calc_checksum(data)]

    def to_bytes(self, header=True):
        temp = bytearray([val if val >= 0 else val + 256 for val in self.to_byte_list(header)])
        # print("\nCommand:")
        # print_hex(temp)
        return temp

    @classmethod
    def from_data(cls, data: bytearray):
        if len(data) < 4:
            return data, None

        # print("\nResponse:")
        # print_hex(data)
        assert data[0] == 255 and data[1] == 255, f"Invalid header {data[0:2]}"

        data_length = data[2]
        if len(data) < data_length + 3:
            return data, None

        cmd = Command()
        cmd.command = data[3]
        cmd.data = data[4 : data_length + 2]
        # print_hex(cmd.data)

        checksum_data = data[2 : data_length + 2]

        assert (
            Command.calc_checksum(checksum_data) == data[data_length + 2]
        ), "Invalid checksum."

        # print(print_hex(data[data_length + 3 : -1]))
        return data[data_length + 3 :], cmd

class BluetoothREPL:
    def __init__(self, device: BluetoothDevice):
        self.device = device
        self.client = BleakClient(device.address, use_cached = False)#, winrt=dict(use_cached_services=False))
        self.processor = ResponseProcessor()
        if device.platform == Platforms.OPTIMUS_PRIME:
            self.state = Optimus()
            self.transform_state = Optimus()
            self.humanoid_state = Optimus()
        elif device.platform == Platforms.GRIMLOCK:
            self.state = Grimlock()
            self.transform_state = Grimlock()
            self.humanoid_state = Grimlock()
        elif device.platform == Platforms.MEGATRON:
            self.state = Megatron()
            self.transform_state = Megatron()
            self.humanoid_state = Megatron()
        else:
            self.state = RobotState()
            self.transform_state = RobotState()
            self.humanoid_state = RobotState()

    async def connect(self) -> bool:
        print(f"Connecting to {self.device.address}...")
        try:
            await self.client.connect()
        except Exception as e:
            print(f"Error: {e}")
            return False
        print("Connected.")
        return True

    async def start_notify(self):
        await self.client.start_notify(
            self.device.notify_uuid, self.notification_handler
        )
        print("Notification started.")

    async def stop_notify(self):
        await self.client.stop_notify(self.device.notify_uuid)
        print("Notification stopped.")

    async def notification_handler(self, sender, data):
        ingest_responses(self.processor.process_response(data), 
                         self.state, 
                         self.transform_state, 
                         self.humanoid_state)

    async def write_command(self, command: Command) -> bool:
        # print( f"Sending {Commands(command.command)} which is value {command.command}")

        try:
            await self.client.write_gatt_char(self.device.write_uuid, command.to_bytes())
        except Exception as e:
            print(f"Error: {e}")
            return False
        return True

    async def disconnect(self):
        try:
            await self.client.disconnect()
        except Exception as e:
            print(f"Error: {e}")
        print("Disconnected.")

class RobotFunctions:
    async def spin_wheel(repl_device: BluetoothREPL, val) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.data["leftWheelSpeed"].locked = False
            repl_device.state.data["rightWheelSpeed"].locked = False
            returnValue = await RobotFunctions.set_locks(repl_device, repl_device.state)
            if returnValue == False:
                return False
            repl_device.state.data["rightWheelSpeed"].value = float(val)
            repl_device.state.data["leftWheelSpeed"].value = -1 * float(val)
            print(repl_device.state)
            returnValue = await repl_device.write_command(
                Command(Commands.SET_POSITION, repl_device.state.to_bytes())
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
            return True

    async def move_servo(repl_device: BluetoothREPL, servo_name: str, val: int) -> bool:
        repl_device.state.data[servo_name].value = float(val)
        print(repl_device.state)
        returnValue = await repl_device.write_command(
            Command(Commands.SET_POSITION, repl_device.state.to_bytes())
        )
        if returnValue == False:
            return False
        await asyncio.sleep(0.02)

    async def stop(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.STOP)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.1)
            returnValue = await repl_device.write_command(
                Command(Commands.STOP)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.1)
            returnValue = await repl_device.write_command(
                Command(Commands.STOP)
            )
            repl_device.state.moving = False
            repl_device.state.transforming = False
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)

    async def transform(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.TRANSFORM, int(0).to_bytes())
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def shutdown(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            return await repl_device.write_command(
                Command(Commands.SHUTDOWN)
            )
        return True

    async def status(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.GET_STATE)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def model(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.MODEL)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def version(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.VERSION)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def firmware(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.FIRMWARE_DATE)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def serial_number(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.SERIAL_NUMBER)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def forward(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.moving = True
            return await repl_device.write_command(
                Command(Commands.FORWARD)
            )
        return True

    async def turn_right(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.moving = True
            return await repl_device.write_command(
                Command(Commands.TURN_RIGHT)
            )
        return True

    async def step_right(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.moving = True
            return await repl_device.write_command(
                Command(Commands.STEP_RIGHT)
            )
        return True

    async def reverse_right(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.moving = True
            return await repl_device.write_command(
                Command(Commands.REVERSE_RIGHT)
            )
        return True

    async def reverse(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.moving = True
            return await repl_device.write_command(
                Command(Commands.REVERSE)
            )
        return True

    async def reverse_left(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.moving = True
            return await repl_device.write_command(
                Command(Commands.REVERSE_LEFT)
            )
        return True

    async def step_left(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.moving = True
            return await repl_device.write_command(
                Command(Commands.STEP_LEFT)
            )
        return True

    async def turn_left(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            repl_device.state.moving = True
            return await repl_device.write_command(
                Command(Commands.TURN_LEFT)
            )
        return True

    async def change_speed(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.GRIMLOCK:
            if repl_device.state.fast_mode == True:
                returnValue = await repl_device.write_command(
                    Command(Commands.BUILT_IN_ACTION, bytearray([3,0]))
                )
            else:
                returnValue = await repl_device.write_command(
                    Command(Commands.BUILT_IN_ACTION, bytearray([3,1]))
                )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def read_directory(repl_device: BluetoothREPL, directory: str) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.READ_DIRECTORY, bytes(directory, 'ascii'))
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def execute_file(repl_device: BluetoothREPL, file: str) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            # print(f"execute_file state.acting = {repl_device.state.acting}")
            repl_device.state.acting = True
            returnValue = await repl_device.write_command(
                Command(Commands.EXECUTE_FILE, bytes(file, 'ascii'))
            )
            # print(f"execute_file state.acting = {repl_device.state.acting}")
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
            # print(f"execute_file state.acting = {repl_device.state.acting}")
        return True

    async def melee(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.BUILT_IN_ACTION, int(4).to_bytes())
            )
            if returnValue == False:
                return False
        elif repl_device.device.platform == Platforms.GRIMLOCK:
            if repl_device.state.robot_mode == True:
                return await RobotFunctions.execute_file(repl_device, "SysAction/Sword")
            else:
                return await RobotFunctions.execute_file(repl_device, "SysAction/Flameout")
        elif repl_device.device.platform == Platforms.MEGATRON:
            if repl_device.state.robot_mode == True:
                return await RobotFunctions.execute_file(repl_device, "SysAction/Sword")
        return True

    async def shoot(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            return await repl_device.write_command(
                Command(Commands.BUILT_IN_ACTION, int(5).to_bytes())
            )
        elif repl_device.device.platform == Platforms.GRIMLOCK:
            if repl_device.state.robot_mode == True:
                return await RobotFunctions.execute_file(repl_device, "SysAction/Shoot")
            else:
                return await RobotFunctions.execute_file(repl_device, "SysAction/Cute")
        elif repl_device.device.platform == Platforms.MEGATRON:
            if repl_device.state.robot_mode == True:
                return await RobotFunctions.execute_file(repl_device, "SysAction/Shoot")
            else:
                return await repl_device.write_command(
                    Command(Commands.BUILT_IN_ACTION, bytearray([3,0]))
                )

    async def random_action(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.BUILT_IN_ACTION, int(7).to_bytes())
            )
            if returnValue == False:
                return False
        elif repl_device.device.platform == Platforms.GRIMLOCK:
            if repl_device.state.robot_mode == True:
                return await RobotFunctions.execute_file(repl_device, "RobotAction/Autobots")
            else:
                return await RobotFunctions.execute_file(repl_device, "Action/Autobots")
        elif repl_device.device.platform == Platforms.MEGATRON:
            if repl_device.state.robot_mode == True:
                return await RobotFunctions.execute_file(repl_device, "SysAction/Hammer")
        return True

    async def prog_init(repl_device: BluetoothREPL, robot_mode: bool) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
        # if repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.ENTER_BLUETOOTH_PROGRAMMING_MODE, int(0).to_bytes() if robot_mode == True else int(1).to_bytes())
            )
            if returnValue == False:
                return False
            await asyncio.sleep(10)
            returnValue = await repl_device.write_command(Command(Commands.GET_POSITION))
            if returnValue == False:
                return False
            await asyncio.sleep(3)
        return True

    async def prog_exit(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
        # if repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.EXIT_BLUETOOTH_PROGRAMMING_MODE)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def load_position(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
        # if repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            if repl_device.state.offsets_initialized == False:
                print("Offsets not initialized! Run prog_init first!")
                return
            returnValue = await repl_device.write_command(
                Command(Commands.GET_POSITION)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def set_position(repl_device: BluetoothREPL, state: RobotState) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
        # if repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            if repl_device.state.offsets_initialized == False:
                print("Offsets not initialized! Run prog_init first!")
                return
            returnValue = await repl_device.write_command(
                Command(Commands.SET_POSITION, state.to_bytes())
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def unlock_all(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.UNLOCK_ALL)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def lock_all(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.LOCK_ALL)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def set_locks(repl_device: BluetoothREPL, state: RobotState) -> bool:
        if repl_device.device.platform == Platforms.OPTIMUS_PRIME:
        # if repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.LOCKS, state.locks_to_bytes())
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True

    async def announce_error(repl_device: BluetoothREPL) -> bool:
        return await RobotFunctions.execute_file(repl_device, "IJustWantHimToComplainHere")

    async def enter_usb_mode(repl_device: BluetoothREPL) -> bool:
        if repl_device.device.platform == Platforms.MEGATRON or repl_device.device.platform == Platforms.GRIMLOCK or repl_device.device.platform == Platforms.OPTIMUS_PRIME:
            returnValue = await repl_device.write_command(
                Command(Commands.ENTER_USB_MODE)
            )
            if returnValue == False:
                return False
            await asyncio.sleep(0.02)
        return True


async def get_first_platform(name: str):
    devices = await BleakScanner.discover(timeout = 10.0)
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
                    return [device.address, Platforms.MEGATRON, name[5:]]
    return ["", Platforms.UNKNOWN, "UNKNOWN"]

async def connect(id: str) -> BluetoothDevice:
    results = await get_first_platform(id)
    found_address = results[0]
    platform = results[1]

    if platform == Platforms.UNKNOWN:
        return None

    device = BluetoothDevice(
        address=found_address,
        write_uuid=UUID_WRITE,
        notify_uuid=UUID_NOTIFY,
        platform=platform,
        id=id
    )

    return device

class IRobot: pass

class IRobot:
    _repl_device: BluetoothREPL | None

    # def __new__(cls):#, *args, **kwargs):
    #     if cls is IRobot:
    #         raise TypeError(f"{cls.__name__} is not capable of processing its members as it is intended as a base class\n"
    #                         f"Instantiate an UnknownState class and call create_robot() to provide a fully functional {cls.__name__} variable.")
    #     return object.__new__(cls)#, *args, **kwargs)

    # def __new__(cls, device: BluetoothREPL):
    #     if cls is IRobot:
    #         raise TypeError(f"{cls.__name__} is not capable of processing its members as it is intended as a base class\n"
    #                         f"Instantiate an UnknownState class and call create_robot() to provide a fully functional {cls.__name__} variable.")
    #     return object.__new__(cls, device)

    def __init__(self):
        print("Really shouldn't use this constructor. Please pass the ID string parameter to the UnknownState constructor.")
        self._repl_device = None

    def __init__(self, device: BluetoothREPL):
        print("Really shouldn't use this constructor. Please pass the ID string parameter to the UnknownState constructor.")
        self._repl_device = None

    def __str__(self) -> str:
        if self._repl_device is not None:
            return f"{self.name()}: IRobot|Battery: {self._repl_device.state.battery}|Robot: {self._repl_device.state.robot_mode}|Fast: {self._repl_device.state.fast_mode}|Moving: {self.moving()}|Acting: {self._repl_device.state.acting}|Transforming: False"
        return "IRobot"

    async def handle_result(self, success: bool) -> bool:
        if success == False:
            print("\n\n\n\n\n\n\n\n\n\n")
            traceback.print_stack()
            await self.disconnect()
        return success

    async def disconnect(self):
        if self._repl_device is None:
            return

        await self._repl_device.stop_notify()
        await self._repl_device.disconnect()
        self._repl_device = None

    async def enter_usb_mode(self):
        if self._repl_device is None:
            return

        await RobotFunctions.enter_usb_mode(self._repl_device)

        await self._repl_device.stop_notify()
        await self._repl_device.disconnect()
        self._repl_device = None

    def name(self) -> str:
        if self._repl_device is not None:
            return self._repl_device.device.id
        return ""

    def platform(self) -> Platforms:
        if self._repl_device is not None:
            return self._repl_device.device.platform
        return Platforms.UNKNOWN

    def offsets_initialized(self) -> bool:
        if self._repl_device is not None:
            return self._repl_device.state.offsets_initialized
        return False

    async def leaving(self):
        return

    def moving(self) -> bool:
        return False

    async def transforming(self) -> bool:
        return False

    def acting(self) -> bool:
        if not (self._repl_device is None):
            return self._repl_device.state.acting
        return False

    def programming_mode(self) -> bool:
        if not (self._repl_device is None):
            return self._repl_device.state.programming_mode
        return False

    async def battery(self) -> int:
        if not (self._repl_device is None):
            await self.status()
            return self._repl_device.state.battery
        return -1

    async def vehicle_mode(self) -> bool:
        if not (self._repl_device is None):
            if not self.acting() and not self.moving():
                await self.status()
            return not self._repl_device.state.robot_mode
        return False

    async def fast_mode(self) -> bool:
        if not (self._repl_device is None):
            await self.status()
            return self._repl_device.state.fast_mode
        return False

    async def transform(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def prog_init(self, robot_mode: bool) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def prog_exit(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def forward(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def turn_right(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def step_right(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def reverse_right(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def reverse(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def reverse_left(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def step_left(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def turn_left(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def horn1(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def horn2(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def stop(self) -> IRobot:
        if not (self._repl_device is None):
            await self.handle_result(await RobotFunctions.stop(self._repl_device))
        return self

    async def shutdown(self) -> IRobot:
        if not (self._repl_device is None):
            await self.handle_result(await RobotFunctions.shutdown(self._repl_device))
        return self

    async def execute_file(self, file: str) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def melee(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def shoot(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def random_action(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return self

    async def status(self):
        if not (self._repl_device is None):
            await self.handle_result(await RobotFunctions.status(self._repl_device))

    async def model(self):
        if not (self._repl_device is None):
            await self.handle_result(await RobotFunctions.model(self._repl_device))

    async def version(self):
        if not (self._repl_device is None):
            await self.handle_result(await RobotFunctions.version(self._repl_device))

    async def firmware(self):
        if not (self._repl_device is None):
            await self.handle_result(await RobotFunctions.firmware(self._repl_device))

    async def serial_number(self):
        if not (self._repl_device is None):
            await self.handle_result(await RobotFunctions.serial_number(self._repl_device))

    async def read_directory(self, directory: str):
        if not (self._repl_device is None):
            await self.handle_result(await RobotFunctions.read_directory(self._repl_device, directory))
        return

    async def change_speed(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return False

    async def load_position(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if self._repl_device.state.offsets_initialized == True:
                    if await self.handle_result(await RobotFunctions.load_position(self._repl_device)):
                        return True
                else:
                    await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return False

    async def get_position(self) -> RobotState | None:
        if not (self._repl_device is None):
            if await self.load_position():
                return self._repl_device.state
            else:
                return None
        return False

    async def get_position_humanoid(self) -> RobotState | None:
        if not (self._repl_device is None):
            if await self.load_position():
                return self._repl_device.humanoid_state
            else:
                return None
        return False

    async def get_position_vehicle(self) -> RobotState | None:
        if not (self._repl_device is None):
            if await self.load_position():
                return self._repl_device.transform_state
            else:
                return None
        return False

    async def set_position(self, state: RobotState) -> bool:
        if state is None:
            print("Empty state received on set_position()")
            return False
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return False

    async def unlock_all(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return False

    async def lock_all(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return False

    async def set_locks(self, state: RobotState) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return False

    async def spin_wheel(self, val) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return False

    async def move_servo(self, servo_name: str, val: int) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting() and not self.moving():
                await self.handle_result(await RobotFunctions.announce_error(self._repl_device))
        return False

class UnknownState(IRobot):
    # def __init__(self):
    #     print("Really shouldn't use this constructor. Please pass the ID string parameter to the UnknownState constructor.")
    #     self._repl_device = None

    def __init__(self):
        self._repl_device = None

    def __str__(self) -> str:
        if self._repl_device is not None:
            return f"{self.name()}: UnknownState | Battery: {self._repl_device.state.battery}|Robot: {self._repl_device.state.robot_mode}|Fast: {self._repl_device.state.fast_mode}|Moving: {self.moving()}|Acting: {self._repl_device.state.acting}|Transforming: False"
        return "UnknownState"

    async def create_robot(self, id: str) -> IRobot:
        device = await connect(id)

        if device is None:
            return None

        self._repl_device = BluetoothREPL(device)

        if self._repl_device is None:
            return None

        await self._repl_device.connect()
        await self._repl_device.start_notify()

        await asyncio.sleep(1)
        returnValue = await self._repl_device.write_command(
            Command(Commands.ACTION_COMPLETE)
        )
        if returnValue == False:
            return None

        returnValue = await RobotFunctions.model(self._repl_device)
        if returnValue == False:
            return None
        await asyncio.sleep(0.1)
        returnValue = await RobotFunctions.version(self._repl_device)
        if returnValue == False:
            return None
        await asyncio.sleep(0.1)
        returnValue = await RobotFunctions.firmware(self._repl_device)
        if returnValue == False:
            return None
        await asyncio.sleep(0.1)
        returnValue = await RobotFunctions.serial_number(self._repl_device)
        if returnValue == False:
            return None
        await asyncio.sleep(0.1)

        returnValue = await self.status()
        if returnValue == False:
            return None
        if self._repl_device.state.robot_mode == True:
            return Robot(self._repl_device)
        else:
            return Vehicle(self._repl_device, time.time() - 5)

class Robot(IRobot):
    def __init__(self, device: BluetoothREPL):
        self._repl_device = device

    def __str__(self) -> str:
        if self._repl_device is not None:
            return f"{self.name()}: Robot|Battery: {self._repl_device.state.battery}|Robot: {self._repl_device.state.robot_mode}|Fast: {self._repl_device.state.fast_mode}|Moving: {self.moving()}|Acting: {self._repl_device.state.acting}|Transforming: {not self._repl_device.state.robot_mode}"
        return "Robot"

    async def transforming(self) -> bool:
        return await self.vehicle_mode()

    async def transform(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                await asyncio.sleep(2)
                if await self.handle_result(await RobotFunctions.transform(self._repl_device)):
                    return Vehicle(self._repl_device, time.time() - 5)
                else:
                    return None
        return self

    async def prog_init(self, robot_mode: bool) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.prog_init(self._repl_device, robot_mode)) == False:
                    return None
                if robot_mode == False and not self._repl_device.platform == Platforms.OPTIMUS_PRIME:
                    return ProgrammingVehicle(self._repl_device)
                else:
                    return ProgrammingRobot(self._repl_device)
        return self

    async def forward(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.forward(self._repl_device)) == False:
                    return None
                return MovingRobot(self._repl_device)
        return self

    async def turn_right(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.turn_right(self._repl_device)) == False:
                    return None
                return MovingRobot(self._repl_device)
        return self

    async def reverse(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.reverse(self._repl_device)) == False:
                    return None
                return MovingRobot(self._repl_device)
        return self

    async def turn_left(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.turn_left(self._repl_device)) == False:
                    return None
                return MovingRobot(self._repl_device)
        return self

    async def step_left(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.step_left(self._repl_device)) == False:
                    return None
                return MovingRobot(self._repl_device)
        return self

    async def step_right(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.step_right(self._repl_device)) == False:
                    return None
                return MovingRobot(self._repl_device)
        return self

    async def execute_file(self, file: str) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                # print(f" Robot execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                self._repl_device.state.acting_progress = 0
                # print(f" Robot execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                if await self.handle_result(await RobotFunctions.execute_file(self._repl_device, file)) == False:
                    return None
                # print(f" Robot execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                if self._repl_device.state.acting_progress == 100:
                    self._repl_device.state.acting = False
                    return self
                while self.acting():
                    await asyncio.sleep(1)
                if await self.handle_result(await self.status()) == False:
                    return None
                await asyncio.sleep(0.1)
                if await self.transforming():
                    return Vehicle(self._repl_device, time.time() - 5)
        return self

    async def melee(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                self._repl_device.state.acting = True
                if await self.handle_result(await RobotFunctions.melee(self._repl_device)) == False:
                    return None
        return self

    async def shoot(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                self._repl_device.state.acting = True
                if await self.handle_result(await RobotFunctions.shoot(self._repl_device)) == False:
                    return None
        return self

    async def random_action(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                self._repl_device.state.acting = True
                if await self.handle_result(await RobotFunctions.random_action(self._repl_device)) == False:
                    return None
        return self

class MovingRobot(IRobot):
    def __init__(self, device: BluetoothREPL):
        self._repl_device = device

    def __str__(self) -> str:
        if self._repl_device is not None:
            return f"{self.name()}: MovingRobot|Battery: {self._repl_device.state.battery}|Robot: {self._repl_device.state.robot_mode}|Fast: {self._repl_device.state.fast_mode}|Moving: {self.moving()}|Acting: {self._repl_device.state.acting}|Transforming: {not self._repl_device.state.robot_mode}"
        return "MovingRobot"

    async def transforming(self) -> bool:
        return await self.vehicle_mode()

    def moving(self) -> bool:
        return True

    async def forward(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.forward(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def turn_right(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.turn_right(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def reverse_right(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.reverse_right(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def reverse(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.reverse(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def reverse_left(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.reverse_left(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def turn_left(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.turn_left(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def step_left(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.step_left(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def step_right(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.step_right(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def stop(self) -> IRobot:
        if not (self._repl_device is None):
            if await self.handle_result(await RobotFunctions.stop(self._repl_device)) == False:
                return None
        return Robot(self._repl_device)

class ProgrammingRobot(IRobot):
    def __init__(self, device: BluetoothREPL):
        self._repl_device = device

    def __str__(self) -> str:
        if self._repl_device is not None:
            return f"{self.name()}: ProgrammingRobot|Battery: {self._repl_device.state.battery}|Robot: {self._repl_device.state.robot_mode}|Fast: {self._repl_device.state.fast_mode}|Moving: {self.moving()}|Acting: {self._repl_device.state.acting}|Transforming: {not self._repl_device.state.robot_mode}"
        return "ProgrammingRobot"

    async def leaving(self):
        # if self._repl_device.device.platform == Platforms.OPTIMUS_PRIME:
        #     self._repl_device.state.data["leftWheelSpeed"].locked = True
        #     self._repl_device.state.data["rightWheelSpeed"].locked = True
        #     self.set_locks(self._repl_device.state)
        return

    async def transforming(self) -> bool:
        return await self.vehicle_mode()

    async def set_position(self, state: RobotState) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.set_position(self._repl_device, state))
        return False

    async def unlock_all(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.unlock_all(self._repl_device))
        return False

    async def lock_all(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.lock_all(self._repl_device))
        return False

    async def set_locks(self, state: RobotState) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.set_locks(self._repl_device, state))
        return False

    async def spin_wheel(self, val) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.spin_wheel(self._repl_device, val))
        return False

    async def move_servo(self, servo_name: str, val: int) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.move_servo(self._repl_device, servo_name, val))
        return False

    async def prog_exit(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                await self.leaving()
                if await self.handle_result(await RobotFunctions.prog_exit(self._repl_device)) == False:
                    return None
                return Robot(self._repl_device)
        return None

    async def execute_file(self, file: str) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                # print(f" ProgrammingRobot execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                self._repl_device.state.acting_progress = 0
                # print(f" ProgrammingRobot execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                if await self.handle_result(await RobotFunctions.execute_file(self._repl_device, file)) == False:
                    return None
                # print(f" ProgrammingRobot execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                if self._repl_device.state.acting_progress == 100:
                    self._repl_device.state.acting = False
                    return self
                # print(f" Acting incomplete")
                while self.acting():
                    await asyncio.sleep(1)
                if await self.handle_result(await self.status()) == False:
                    # print(f" Status failed... Error")
                    return None
                await asyncio.sleep(0.1)
                if await self.transforming():
                    # print(f" Transforming... assuming vehicle execution")
                    return ProgrammingVehicle(self._repl_device)
        return self

class Vehicle(IRobot):
    horn_time: float

    def __init__(self, device: BluetoothREPL, time1: float):
        self._repl_device = device
        self.horn_time = time1

    def __str__(self) -> str:
        if self._repl_device is not None:
            return f"{self.name()}: Vehicle|Battery: {self._repl_device.state.battery}|Robot: {self._repl_device.state.robot_mode}|Fast: {self._repl_device.state.fast_mode}|Moving: {self.moving()}|Acting: {self._repl_device.state.acting}|Transforming: {self._repl_device.state.robot_mode}"
        return "Vehicle"

    async def transforming(self) -> bool:
        return not await self.vehicle_mode()

    async def transform(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                await asyncio.sleep(1)
                if await self.handle_result(await RobotFunctions.transform(self._repl_device)):
                    return Robot(self._repl_device)
                else:
                    return None
        return self

    async def prog_init(self, robot_mode: bool) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.prog_init(self._repl_device, robot_mode)) == False:
                    return None
                if robot_mode == False and not self._repl_device.platform == Platforms.OPTIMUS_PRIME:
                    return ProgrammingVehicle(self._repl_device)
                else:
                    return ProgrammingRobot(self._repl_device)
        return self

    async def forward(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.forward(self._repl_device)) == False:
                    return None
                return MovingVehicle(self._repl_device)
        return self

    async def turn_right(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.turn_right(self._repl_device)) == False:
                    return None
                return MovingVehicle(self._repl_device)
        return self

    async def reverse_right(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.reverse_right(self._repl_device)) == False:
                    return None
                return MovingVehicle(self._repl_device)
        return self

    async def reverse(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.reverse(self._repl_device)) == False:
                    return None
                return MovingVehicle(self._repl_device)
        return self

    async def reverse_left(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.reverse_left(self._repl_device)) == False:
                    return None
                return MovingVehicle(self._repl_device)
        return self

    async def turn_left(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.turn_left(self._repl_device)) == False:
                    return None
                return MovingVehicle(self._repl_device)
        return self

    async def step_left(self) -> IRobot:
        if not (self._repl_device is None):
            if self.platform() == Platforms.OPTIMUS_PRIME:
                return await self.horn1()
            else:
                if not await self.transforming() and not self.acting():
                    if await self.handle_result(await RobotFunctions.step_left(self._repl_device)) == False:
                        return None
                    return MovingVehicle(self._repl_device)
        return self

    async def step_right(self) -> IRobot:
        if not (self._repl_device is None):
            if self.platform() == Platforms.OPTIMUS_PRIME:
                return await self.horn2()
            else:
                if not await self.transforming() and not self.acting():
                    if await self.handle_result(await RobotFunctions.step_right(self._repl_device)) == False:
                        return None
                    return MovingVehicle(self._repl_device)
        return self

    async def horn1(self) -> IRobot:
        if not (self._repl_device is None) and self.horn_time + 5 < time.time():
            if not await self.transforming() and not self.acting():
                self.horn_time = time.time()
                if await self.handle_result(await RobotFunctions.step_left(self._repl_device)) == False:
                    return None
        return self

    async def horn2(self) -> IRobot:
        if not (self._repl_device is None) and self.horn_time + 5 < time.time():
            if not await self.transforming() and not self.acting():
                self.horn_time = time.time()
                if await self.handle_result(await RobotFunctions.step_right(self._repl_device)) == False:
                    return None
        return self

    async def stop(self) -> IRobot:
        if not (self._repl_device is None):
            if await self.handle_result(await RobotFunctions.stop(self._repl_device)) == False:
                return None
        return self

    async def execute_file(self, file: str) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                # print(f" Vehicle execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                self._repl_device.state.acting_progress = 0
                # print(f" Vehicle execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                if await self.handle_result(await RobotFunctions.execute_file(self._repl_device, file)) == False:
                    return None
                # print(f" Vehicle execute_file state.acting_progress = {self._repl_device.state.acting_progress}")
                if self._repl_device.state.acting_progress == 100:
                    self._repl_device.state.acting = False
                    return self
                while self.acting():
                    await asyncio.sleep(1)
                if await self.handle_result(await self.status()) == False:
                    return None
                await asyncio.sleep(0.1)
                if await self.transforming():
                    return Robot(self._repl_device)
        return self

    async def change_speed(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if self._repl_device.device.platform != Platforms.OPTIMUS_PRIME:
                    return await self.handle_result(await RobotFunctions.change_speed(self._repl_device))
        return False

    async def melee(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.melee(self._repl_device)) == False:
                    return None
        return self

    async def shoot(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.shoot(self._repl_device)) == False:
                    return None
        return self

    async def random_action(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.random_action(self._repl_device)) == False:
                    return None
        return self

class MovingVehicle(IRobot):
    def __init__(self, device: BluetoothREPL):
        self._repl_device = device

    def __str__(self) -> str:
        if self._repl_device is not None:
            return f"{self.name()}: MovingVehicle|Battery: {self._repl_device.state.battery}|Robot: {self._repl_device.state.robot_mode}|Fast: {self._repl_device.state.fast_mode}|Moving: {self.moving()}|Acting: {self._repl_device.state.acting}|Transforming: {self._repl_device.state.robot_mode}"
        return "MovingVehicle"

    async def transforming(self) -> bool:
        return not await self.vehicle_mode()

    def moving(self) -> bool:
        return True

    async def forward(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.forward(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def turn_right(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.turn_right(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def reverse_right(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.reverse_right(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def reverse(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.reverse(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def reverse_left(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.reverse_left(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def turn_left(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.turn_left(self._repl_device) == False:
                self.stop()
                return None
            return self
        return self

    async def step_left(self) -> IRobot:
        if not (self._repl_device is None):
            if self.platform() == Platforms.OPTIMUS_PRIME:
                return await self.horn1()
            else:
                if await RobotFunctions.step_left(self._repl_device) == False:
                    self.stop()
                    return None
                return self
        return self

    async def step_right(self) -> IRobot:
        if not (self._repl_device is None):
            if self.platform() == Platforms.OPTIMUS_PRIME:
                return await self.horn2()
            else:
                if await RobotFunctions.step_right(self._repl_device) == False:
                    self.stop()
                    return None
                return self
        return self

    async def horn1(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.step_left(self._repl_device) == False:
                self.stop()
                return None
        return Vehicle(self._repl_device, time.time())

    async def horn2(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.step_right(self._repl_device) == False:
                self.stop()
                return None
        return Vehicle(self._repl_device, time.time())

    async def stop(self) -> IRobot:
        if not (self._repl_device is None):
            if await RobotFunctions.stop(self._repl_device) == False:
                return None
        return Vehicle(self._repl_device, time.time() - 5)

class ProgrammingVehicle(IRobot):
    def __init__(self, device: BluetoothREPL):
        self._repl_device = device

    def __str__(self) -> str:
        if self._repl_device is not None:
            return f"{self.name()}: ProgrammingVehicle|Battery: {self._repl_device.state.battery}|Robot: {self._repl_device.state.robot_mode}|Fast: {self._repl_device.state.fast_mode}|Moving: {self.moving()}|Acting: {self._repl_device.state.acting}|Transforming: {self._repl_device.state.robot_mode}"
        return "ProgrammingVehicle"

    async def transforming(self) -> bool:
        return not await self.vehicle_mode()

    async def set_position(self, state: RobotState) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.set_position(self._repl_device, state))
        return False

    async def unlock_all(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.unlock_all(self._repl_device))
        return False

    async def lock_all(self) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.lock_all(self._repl_device))
        return False

    async def set_locks(self, state: RobotState) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.set_locks(self._repl_device, state))
        return False

    async def spin_wheel(self, val) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.spin_wheel(self._repl_device, val))
        return False

    async def move_servo(self, servo_name: str, val: int) -> bool:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                return await self.handle_result(await RobotFunctions.move_servo(self._repl_device, servo_name, val))
        return False

    async def prog_exit(self) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.prog_exit(self._repl_device)) == False:
                    return None
                return Robot(self._repl_device)
        return None

    async def execute_file(self, file: str) -> IRobot:
        if not (self._repl_device is None):
            if not await self.transforming() and not self.acting():
                if await self.handle_result(await RobotFunctions.execute_file(self._repl_device, file)) == False:
                    return None
                while self.acting():
                    await asyncio.sleep(1)
                if await self.handle_result(await self.status()) == False:
                    return None
                await asyncio.sleep(0.1)
                if await self.transforming():
                    return ProgrammingRobot(self._repl_device)
        return self

class RobotWrapper:
    robot: IRobot | None

    def __init__(self):
        self.robot = None
        
    def __str__(self) -> str:
        if self.robot is not None:
            return f"{self.robot}"
        return "No robot connected"
    
    def connected(self):
        return (self.robot is not None)

    async def create_robot(self, id: str):
        self.robot = await UnknownState().create_robot(id)

    async def disconnect(self):
        if self.connected():
            await self.robot.disconnect()
            self.robot = None

    async def enter_usb_mode(self):
        if self.connected():
            await self.robot.enter_usb_mode()
            self.robot = None

    def name(self) -> str:
        if self.connected():
            return self.robot.name()
        else:
            return "No robot connected"

    def platform(self) -> Platforms:
        if self.connected():
            return self.robot.platform()
        else:
            return Platforms.UNKNOWN

    def offsets_initialized(self) -> bool:
        if self.connected():
            return self.robot.offsets_initialized()
        else:
            return False

    def moving(self) -> bool:
        if self.connected():
            return self.robot.moving()
        else:
            return False

    async def transforming(self) -> bool:
        if self.connected():
            return await self.robot.transforming()
        else:
            return False

    def acting(self) -> bool:
        if self.connected():
            return self.robot.acting()
        else:
            return False

    def programming_mode(self) -> bool:
        if self.connected():
            return self.robot.programming_mode()
        else:
            return False

    async def battery(self) -> int:
        if self.connected():
            return await self.robot.battery()
        else:
            return -1

    async def vehicle_mode(self) -> bool:
        if self.connected():
            return await self.robot.vehicle_mode()
        else:
            return False

    async def fast_mode(self) -> bool:
        if self.connected():
            return await self.robot.fast_mode()
        else:
            return False

    async def transform(self):
        if self.connected():
            self.robot = await self.robot.transform()

    async def prog_init(self, robot_mode: bool):
        if self.connected():
            self.robot = await self.robot.prog_init(robot_mode)

    async def prog_exit(self):
        if self.connected():
            self.robot = await self.robot.prog_exit()

    async def forward(self):
        if self.connected():
            self.robot = await self.robot.forward()

    async def turn_right(self):
        if self.connected():
            self.robot = await self.robot.turn_right()

    async def step_right(self):
        if self.connected():
            self.robot = await self.robot.step_right()

    async def reverse_right(self):
        if self.connected():
            self.robot = await self.robot.reverse_right()

    async def reverse(self):
        if self.connected():
            self.robot = await self.robot.reverse()

    async def reverse_left(self):
        if self.connected():
            self.robot = await self.robot.reverse_left()

    async def step_left(self):
        if self.connected():
            self.robot = await self.robot.step_left()

    async def turn_left(self):
        if self.connected():
            self.robot = await self.robot.turn_left()

    async def horn1(self):
        if self.connected():
            self.robot = await self.robot.horn1()

    async def horn2(self):
        if self.connected():
            self.robot = await self.robot.horn2()

    async def stop(self):
        if self.connected():
            self.robot = await self.robot.stop()

    async def shutdown(self):
        if self.connected():
            self.robot = await self.robot.shutdown()

    async def execute_file(self, file: str):
        if self.connected():
            self.robot = await self.robot.execute_file(file)

    async def melee(self):
        if self.connected():
            self.robot = await self.robot.melee()

    async def shoot(self):
        if self.connected():
            self.robot = await self.robot.shoot()

    async def random_action(self):
        if self.connected():
            self.robot = await self.robot.random_action()

    async def status(self):
        if self.connected():
            await self.robot.status()

    async def model(self):
        if self.connected():
            await self.robot.model()

    async def version(self):
        if self.connected():
            await self.robot.version()

    async def firmware(self):
        if self.connected():
            await self.robot.firmware()

    async def serial_number(self):
        if self.connected():
            await self.robot.serial_number()

    async def read_directory(self, directory: str):
        if self.connected():
            await self.robot.read_directory(directory)

    async def change_speed(self) -> bool:
        if self.connected():
            return await self.robot.change_speed()
        else:
            return False

    async def load_position(self) -> bool:
        if self.connected():
            return await self.robot.load_position()
        else:
            return False

    async def get_position(self) -> RobotState | None:
        if self.connected():
            return await self.robot.get_position()
        else:
            return None

    async def get_position_humanoid(self) -> RobotState | None:
        if self.connected():
            return await self.robot.get_position_humanoid()
        else:
            return None

    async def get_position_vehicle(self) -> RobotState | None:
        if self.connected():
            return await self.robot.get_position_vehicle()
        else:
            return None

    async def set_position(self, state: RobotState) -> bool:
        if self.connected():
            return await self.robot.set_position(state)
        else:
            return False

    async def unlock_all(self) -> bool:
        if self.connected():
            return await self.robot.unlock_all()
        else:
            return False

    async def lock_all(self) -> bool:
        if self.connected():
            return await self.robot.lock_all()
        else:
            return False

    async def set_locks(self, state: RobotState) -> bool:
        if self.connected():
            return await self.robot.set_locks(state)
        else:
            return False

    async def spin_wheel(self, val) -> bool:
        if self.connected():
            return await self.robot.spin_wheel(val)
        else:
            return False

    async def move_servo(self, servo_name: str, val: int) -> bool:
        if self.connected():
            return await self.robot.move_servo(servo_name, val)
        else:
            return False

class IRobotHandler:
    def __new__(cls, *args, **kwargs):
        if cls is IRobotHandler:
            raise TypeError(f"Interface {cls.__name__} is being instantiated directly.\n"
                            f"Create a class that inherits {cls.__name__} and create your own handling in its run() function.")
        return object.__new__(cls, *args, **kwargs)

    # After creating your handler run this as the parameter in a call to asyncio.run()
    async def run():
        robot = []
        robot[0] = RobotWrapper()
        robot[0].create_robot("Bluetooth name of robot")
        # Continue creating until all robots connected

        while True:
            # Run your code here.
            # 1) Remember to break out of your while loop and 
            # 2) Remember to call await asyncio.sleep() occasionally to receive and process messages)
            await asyncio.sleep(0.02)
            robot[0].transform()
            while robot[0].transforming() == True:
                await asyncio.sleep(0.2)
            break

        await robot[0].disconnect()
        # Continue until all robots disconnected

        return

@dataclass
class ResponseProcessor:
    buffer: bytearray = field(default_factory=bytearray)

    def process_response(self, data):
        self.buffer += data
        commands = []

        while len(self.buffer) > 0:
            # Attempt to create the command response.
            # If we have insufficient bytes, then no command will be
            # created and the returned buffer will be the same as
            # the input buffer.
            self.buffer, command = Command.from_data(self.buffer)

            if not command:
                break
            commands.append(command)

        return commands


@dataclass
class Response:
    data: list[int] | bytearray

    def __post_init__(self):
        self.data = list(self.data)

    def __str__(self) -> str:
        return "Response()"


def pad_list_with_zeros(data, length):
    """
    Pad a list with zeros to the specified length.

    Parameters:
    data (list): The list of values to pad.
    length (int): The desired length of the list after padding.

    Returns:
    list: The padded list.
    """
    if len(data) > length:
        raise ValueError("The specified length is shorter than the original list length.")
    return data + [0] * (length - len(data))

def byte_list_to_hex_string(byte_list):
    """
    Convert a list of byte values to a hex string.

    Parameters:
    byte_list (list of int): The list of byte values to convert.

    Returns:
    str: The hex string representation of the byte values.
    """
    hex_string = "".join(
        f"{(byte if byte >= 0 else byte + 256):02X}" for byte in byte_list
    )
    return hex_string


def hex_string_to_byte_list(hex_string):
    """
    Convert a hex string to a list of byte values, ignoring all whitespace.

    Parameters:
    hex_string (str): The hex string to convert.

    Returns:
    list of int: The list of byte values.
    """
    # Remove all whitespace from the hex string
    hex_string = "".join(hex_string.split())

    # Ensure the hex string has an even number of characters
    if len(hex_string) % 2 != 0:
        raise ValueError("Hex string has an odd number of characters")

    byte_list = [int(hex_string[i : i + 2], 16) for i in range(0, len(hex_string), 2)]
    return byte_list


def print_dataclass_values(instance):
    """
    Print all named values in a dataclass instance.

    Parameters:
    instance (dataclass): The dataclass instance to iterate over.
    """
    for field, value in instance.data.items():
        print(f"{field}: {value.value}")


def checksum(data: list):
    data_length = len(data) + 1
    checksum = sum(data, data_length) % 256
    return checksum
    # self.write_data.append([255, 255, data_length, *data, checksum])
    # self.send_data()

control_chars = ''.join(map(chr, itertools.chain(range(0x00,0x20), range(0x7f,0xa0))))

control_char_re = re.compile('[%s]' % re.escape(control_chars))

def remove_control_chars(s):
    return control_char_re.sub('', s)

def replace_control_chars(s):
    return control_char_re.sub('.', s)

def print_hex(byte_array):
    """
    Print the hexadecimal representation of a bytearray.

    Parameters:
    byte_array (bytearray): The bytearray to print in hex.
    """
    hex_string = byte_array.hex()
    formatted_hex = ' '.join(hex_string[i:i+2] for i in range(0, len(hex_string), 2))
    char_array = bytearray(len(byte_array))
    char_array[:] = byte_array
    for i in range(0, len(char_array), 1):
        if char_array[i] > 0x7e or char_array[i] < 0x20:
            char_array[i] = 0x2e
    char_string = char_array.decode(encoding='ascii')
    replace_control_chars(char_string)
    formatted_string = '  '.join(char_string[i:i+1] for i in range(0, len(char_string), 1))
    print(f"Hexadecimal: {formatted_hex}")
    print(f"Character  : {formatted_string}")

def ingest_responses(commands, state: RobotState, transform_state: RobotState, humanoid_state: RobotState ):

    hand_shake = 0
    for command in commands:
        # print( f"Received {Commands(command.command)} which is value {command.command}")

        # print( f"Checking for Commands.ENTER_BLUETOOTH_PROGRAMMING_MODE {Commands.ENTER_BLUETOOTH_PROGRAMMING_MODE.value}")
        if command.command == Commands.ENTER_BLUETOOTH_PROGRAMMING_MODE.value:
            if len(command.data) == 48:
                if hand_shake == 0:
                    state.offsets_from_bytes(command.data)
                    transform_state.offsets_from_bytes(command.data)
                    humanoid_state.offsets_from_bytes(command.data)
                    print("Offsets:")
                    print_hex(command.data)

                if hand_shake == 1:
                    transform_state.from_bytes(command.data)

                if hand_shake == 2:
                    humanoid_state.from_bytes(command.data)

                hand_shake += 1
            state.programming_mode = True

        # print( f"Checking for Commands.EXIT_BLUETOOTH_PROGRAMMING_MODE {Commands.EXIT_BLUETOOTH_PROGRAMMING_MODE.value}")
        elif command.command == Commands.EXIT_BLUETOOTH_PROGRAMMING_MODE.value:
            state.programming_mode = False

        # print( f"Checking for Commands.ACTION_COMPLETE {Commands.ACTION_COMPLETE.value}")
        elif command.command == Commands.ACTION_COMPLETE.value:
            # print(f" ingest_responses state.acting = {state.acting}")
            state.acting = False
            # print(f" ingest_responses state.acting = {state.acting}")

        # print( f"Checking for Commands.GET_POSITION {Commands.GET_POSITION.value}")
        elif command.command == Commands.GET_POSITION.value:
            if len(command.data) == 48:
                state.from_bytes(command.data)
                print("Updated Position: ", state)

        # print( f"Checking for Commands.GET_STATE {Commands.GET_STATE.value}")
        elif command.command == Commands.GET_STATE.value:
            if len(command.data) > 2:
                state.robot_mode = (command.data[0] == 0)
                state.battery = command.data[1]
            if len(command.data) > 5:
                state.fast_mode = (command.data[5] == 1)

        # print( f"Checking for Commands.ACTION_PROGRESS {Commands.ACTION_PROGRESS.value} or Commands.EXECUTE_FILE {Commands.EXECUTE_FILE.value}")
        # if command.command == Commands.BUILT_IN_ACTION.value or command.command == Commands.ACTION_PROGRESS.value or command.command == Commands.EXECUTE_FILE.value:
        elif command.command == Commands.ACTION_PROGRESS.value or command.command == Commands.EXECUTE_FILE.value:
            if len(command.data) > 0:
                # print(f" ingest_responses state.acting_progress = {state.acting_progress}")
                state.acting_progress = command.data[0]
                # print(f" ingest_responses state.acting_progress = {state.acting_progress}")
                if state.acting_progress == 100:
                    # print(f" ingest_responses state.acting = {state.acting}")
                    state.acting = False
                    # print(f" ingest_responses state.acting = {state.acting}")

        # print( f"Checking for Commands.READ_DIRECTORY {Commands.READ_DIRECTORY.value}")
        elif command.command == Commands.READ_DIRECTORY.value:
            print(bytearray(command.data).decode())

# Example usage
if __name__ == "__main__":

    optimus = Optimus()
    optimus2 = Optimus()
    robot = RobotState()
    dropMe = RobotState()

    grimlock_robot_response_data = hex_string_to_byte_list(
        """
        ffff 32e6 6286 5580 7f96 81aa 7f81 c8b1 
        7d7e 2139 4e80 80de 222b b4d3 ca4e 1d1c 
        5e9b d782 9c77 0000 fa00 0000 0000 0000 
        0000 0000 93ff ff32 e65c 5dea 7883 9aaa
        1885 7d9f b27d 7ed5 624c 7f7e 27b0 29b2
        45c8 509f add8 2222 82db 7800 0000 0000
        fa00 0000 0000 0000 0026 ffff 03e6 e6cf
        """
    )

    processor = ResponseProcessor()
    commands = processor.process_response(bytearray(grimlock_robot_response_data))
    print(commands)

    optimus_response_data = hex_string_to_byte_list(
        """
        FF FF32 E67A 7A59 867C 7775 9B71
        824B 4FBF 7581 C4AE A739 7982 34CB 534F
        0000 7D7D 7D7D 7D7D 7D7D 7D7D 7D7D 7D7D
        7D7D 7D7D 7D7D 7D5F FFFF 32E6 797A 59DD
        8179 7499 1B7F A84E C1D2 DF0C 52A9 381B
        26EA 15A9 B100 007D 7D7D 7D7D 7D7D 7D7D
        7D7D 7D7D 7D7D 7D7D 7D7D 7D7D 64FF FF32
        E67B 988B 9B7C 7757 6A5D 834B 4FBF 7581
        C5AE A839 7981 34CB 534F 0000 7D7D 7D7D
        7D7D 7D7D 7D7D 7D7D 7D7D 7D7D 7D7D 7D7D
        7D64"""
    )

    processor = ResponseProcessor()
    commands = processor.process_response(bytearray(optimus_response_data))
    print(commands)

    ingest_responses(commands, optimus, dropMe, dropMe)
    ingest_responses(commands, optimus2, dropMe, dropMe)
    ingest_responses(commands, robot, dropMe, dropMe)

    # data = hex_string_to_byte_list(
    #     """
    #     FFFF 33E8 7A7A 5986 7C77 759B 7182 4B4F
    #     BF75 E0C4 AEA7 3979 8234 CB53 4F00 0000
    #     0000 0000 0000 0000 0000 0000 0000 0000
    #     0000 0000 28
    # """
    # )
    # data = hex_string_to_byte_list("""
    #     7A7A 5986 7C77 759B 7182 4B4F
    #     BF75 E0C4 AEA7 3979 8234 CB53 4F
    # """)

    print(byte_list_to_hex_string(Command(Commands.GET_STATE).to_bytes()))

    # data = [*pad_list_with_zeros(data, 48), 40]
    # print(
    #     byte_list_to_hex_string(
    #         Command(Commands.SET_POSITION, data).to_bytes()
    #     )
    # )


    data = hex_string_to_byte_list("""
        7A7A 5986 7C77 759B 7182 4B4F
        BF75 E0C4 AEA7 3979 8234 CB53
        4F00 00
    """)

    optimus2.from_bytes(data)

    print(
        byte_list_to_hex_string(
            Command(Commands.SET_POSITION, optimus2.to_bytes()).to_bytes()
        )
    )

    print_hex(Command(Commands.ENTER_BLUETOOTH_PROGRAMMING_MODE).to_bytes())

    robot.from_bytes(commands[2].data)
    print_hex(bytearray(commands[2].data))
    print_hex(robot.to_bytes())

    # print(interpolate(optimus, optimus2, 10, linear))
