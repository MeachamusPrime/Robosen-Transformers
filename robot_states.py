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

from dataclasses import dataclass

def calculate_signed_value(num):
    if num > 127:
        # Convert to signed 8-bit integer
        return num - 256
    else:
        return num

def calculate_twos_complement(num):
    if num < 0:
        # Convert to two's complement integer
        return num + 256
    else:
        return num

def linear(start, end, interval):
    return (end - start) / interval

@dataclass
class RobotAction:
    data: dict
    interval: int
    time: int

@dataclass
class Servo:
    org: str
    init_value: int
    first_value: int
    init_lock: bool
    label: str
    min: int
    max: int
    data_index: int
    locked: bool = False
    offset: int | None = None
    is_related_same: bool = False
    value: float = 0.0
    interpolation: callable = linear

    def __post_init__(self):
        self.value = self.init_value

@dataclass
class RobotState:
    data: dict | None = None
    action: RobotAction | None = None
    offsets_initialized: bool = False
    moving: bool = False
    transforming: bool = False
    battery: int = 100
    fast_mode: bool = False
    robot_mode: bool = False
    programming_mode: bool = False
    acting: bool = False
    acting_progress: int = 0

    def to_byte_list(self):
        data = [0] * 48 + [40]

        for value in self.data.values():
            assert value.offset is not None, "Failed to set offsets!"

            val = int(value.value)

            if val > value.max:
                val = value.max
            if val < value.min:
                val = value.min

            # Check for wheels
            if value.label == "leftWheelSpeed" or value.label == "rightWheelSpeed":
                val = calculate_twos_complement(val)

            data[value.data_index] = val + value.offset

        return data

    def to_bytes(self):
        return bytearray(self.to_byte_list())

    def locks_to_byte_list(self):
        data = [0] * 48

        for value in self.data.values():
            data[value.data_index] = 0 if value.locked else 1

        return data

    def locks_to_bytes(self):
        return bytearray(self.locks_to_byte_list())

    def from_bytes(self, data: list[int]):
        for value in self.data.values():
            assert value.offset is not None, "Failed to set offsets!"

            val = data[value.data_index] - value.offset

            if val > value.max:
                val = value.max
            if val < value.min:
                val = value.min

            if value.label == "leftWheelSpeed" or value.label == "rightWheelSpeed":
                val = calculate_signed_value(val)

            value.value = float(val)

        return data

    def offsets_from_bytes(self, data: list[int]):
        for key in self.data.keys():
            self.data[key].offset = data[self.data[key].data_index]
        self.offsets_initialized = True

    def __str__(self):
        s = "RobotState(\n"
        for key, value in self.data.items():
            s += f"{key}: {value.value} {value.data_index}\n"
        s += ")"
        return s

    def move_to(self, to, time, method):
        assert time >= 0, "Interval must be a positive integer."

        interval = int(time * 10)

        deltas = {
            key: method(self.data[key].value, to.data[key].value, interval)
            for key in self.data.keys()
        }
        self.action = RobotAction(data=deltas, interval=interval, time=time)

    def has_action(self):
        return self.action is not None

    def next(self) -> bool:
        """
        while running:
          if robot.next():
              connection.setPosition(robot)
        """
        if not self.has_action():
            return False

        for key in self.data.keys():
            self.data[key].value += self.action.data[key]

        self.action.interval -= 1

        if self.action.interval == 0:
            self.action = None

        return True

    def __post_init__(self):
        self.data = {}

@dataclass
class Optimus(RobotState):
    def __post_init__(self):
        self.data = {
            "rightHip": Servo(
                org="rightLeg",
                init_value=0,
                first_value=8,
                init_lock=True,
                label="rightHip",
                min=0,
                max=40,
                data_index=5,
                is_related_same=False,
            ),
            "rightThigh": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightThigh",
                min=-95,
                max=95,
                data_index=6,
                is_related_same=False,
            ),
            "rightKnee": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightCalf",
                min=-95,
                max=30,
                data_index=7,
                is_related_same=False,
            ),
            "rightAnkle": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightAnkle",
                min=-95,
                max=80,
                data_index=8,
                is_related_same=False,
            ),
            "rightFoot": Servo(
                org="rightLeg",
                init_value=0,
                first_value=-8,
                init_lock=True,
                label="rightFoot",
                min=-20,
                max=40,
                data_index=9,
                is_related_same=False,
            ),
            "leftHip": Servo(
                org="leftLeg",
                init_value=0,
                first_value=-8,
                init_lock=True,
                label="leftHip",
                min=0,
                max=40,
                data_index=0,
                is_related_same=False,
            ),
            "leftThigh": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftThigh",
                min=-95,
                max=95,
                data_index=1,
                is_related_same=False,
            ),
            "leftKnee": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftCalf",
                min=-30,
                max=95,
                data_index=2,
                is_related_same=False,
            ),
            "leftAnkle": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftAnkle",
                min=-80,
                max=95,
                data_index=3,
                is_related_same=False,
            ),
            "leftFoot": Servo(
                org="leftLeg",
                init_value=0,
                first_value=8,
                init_lock=True,
                label="leftFoot",
                min=-40,
                max=20,
                data_index=4,
                is_related_same=False,
            ),
            "rightScapula": Servo(
                org="rightArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightScapula",
                min=-95,
                max=0,
                data_index=16,
                is_related_same=False,
            ),
            "rightShoulder": Servo(
                org="rightArm",
                init_value=0,
                first_value=15,
                init_lock=True,
                label="rightShoulder",
                min=-90,
                max=0,
                data_index=17,
                is_related_same=False,
            ),
            "rightArm": Servo(
                org="rightArm",
                init_value=0,
                first_value=15,
                init_lock=True,
                label="rightUpperArm",
                min=-30,
                max=185,
                data_index=18,
                is_related_same=False,
            ),
            "rightUpperArm": Servo(
                org="rightArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightElbow",
                min=-95,
                max=95,
                data_index=19,
                is_related_same=False,
            ),
            "rightElbow": Servo(
                org="rightArm",
                init_value=0,
                first_value=30,
                init_lock=True,
                label="rightLowerArm",
                min=-95,
                max=60,
                data_index=20,
                is_related_same=False,
            ),
            "rightWrist": Servo(
                org="rightArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightWrist",
                min=-40,
                max=185,
                data_index=21,
                is_related_same=False,
            ),
            "leftScapula": Servo(
                org="leftArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftScapula",
                min=0,
                max=95,
                data_index=10,
                is_related_same=False,
            ),
            "leftShoulder": Servo(
                org="leftArm",
                init_value=0,
                first_value=-15,
                init_lock=True,
                label="leftShoulder",
                min=0,
                max=90,
                data_index=11,
                is_related_same=False,
            ),
            "leftArm": Servo(
                org="leftArm",
                init_value=0,
                first_value=-15,
                init_lock=True,
                label="leftUpperArm",
                min=-185,
                max=30,
                data_index=12,
                is_related_same=False,
            ),
            "leftUpperArm": Servo(
                org="leftArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftElbow",
                min=-95,
                max=95,
                data_index=13,
                is_related_same=False,
            ),
            "leftElbow": Servo(
                org="leftArm",
                init_value=0,
                first_value=-30,
                init_lock=True,
                label="leftLowerArm",
                min=-60,
                max=95,
                data_index=14,
                is_related_same=False,
            ),
            "leftWrist": Servo(
                org="leftArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftWrist",
                min=-30,
                max=185,
                data_index=15,
                is_related_same=False,
            ),
            "waist": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="waist",
                min=-185,
                max=40,
                data_index=22,
                is_related_same=False,
            ),
            "abdomen": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="abdomen",
                min=-15,
                max=95,
                data_index=23,
            ),
            "head": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="head",
                min=0,
                max=105,
                data_index=24,
            ),
            "rightWheelSpeed": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=False,
                label="rightWheelSpeed",
                min=-100,
                max=100,
                data_index=26,
                locked=True,
                is_related_same=False,
            ),
            "leftWheelSpeed": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=False,
                label="leftWheelSpeed",
                min=-100,
                max=100,
                data_index=25,
                locked=True,
                is_related_same=False,
            ),
        }

@dataclass
class Grimlock(RobotState):
    def __post_init__(self):
        self.data = {
            "rightHip": Servo(
                org="rightLeg",
                init_value=0,
                first_value=8,
                init_lock=True,
                label="rightHip",
                min=-60,
                max=5,
                data_index=5,
                is_related_same=False,
            ),
            "rightThigh": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightThigh",
                min=-90,
                max=60,
                data_index=6,
                is_related_same=False,
            ),
            "rightKnee": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightKnee",
                min=-80,
                max=0,
                data_index=7,
                is_related_same=False,
            ),
            "rightAnkle": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightAnkle",
                min=-50,
                max=30,
                data_index=8,
                is_related_same=False,
            ),
            "rightFoot": Servo(
                org="rightLeg",
                init_value=0,
                first_value=-8,
                init_lock=True,
                label="rightFoot",
                min=-10,
                max=60,
                data_index=9,
                is_related_same=False,
            ),
            "leftHip": Servo(
                org="leftLeg",
                init_value=0,
                first_value=-8,
                init_lock=True,
                label="leftHip",
                min=-5,
                max=60,
                data_index=0,
                is_related_same=False,
            ),
            "leftThigh": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftThigh",
                min=-60,
                max=90,
                data_index=1,
                is_related_same=False,
            ),
            "leftKnee": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftKnee",
                min=0,
                max=80,
                data_index=2,
                is_related_same=False,
            ),
            "leftAnkle": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftAnkle",
                min=-30,
                max=50,
                data_index=3,
                is_related_same=False,
            ),
            "leftFoot": Servo(
                org="leftLeg",
                init_value=0,
                first_value=8,
                init_lock=True,
                label="leftFoot",
                min=-60,
                max=10,
                data_index=4,
                is_related_same=False,
            ),
            # "rightScapula": Servo(
            #     org="rightArm",
            #     init_value=0,
            #     first_value=0,
            #     init_lock=True,
            #     label="rightScapula",
            #     min=0,
            #     max=95,
            #     data_index=16,
            #     is_related_same=False,
            # ),
            "rightShoulder": Servo(
                org="rightArm",
                init_value=0,
                first_value=15,
                init_lock=True,
                label="rightShoulder",
                min=-40,
                max=180,
                data_index=17,
                is_related_same=False,
            ),
            "rightArm": Servo(
                org="rightArm",
                init_value=0,
                first_value=15,
                init_lock=True,
                label="rightUpperArm",
                min=-5,
                max=60,
                data_index=18,
                is_related_same=False,
            ),
            "rightUpperArm": Servo(
                org="rightArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightElbow",
                min=-100,
                max=100,
                data_index=19,
                is_related_same=False,
            ),
            "rightElbow": Servo(
                org="rightArm",
                init_value=0,
                first_value=30,
                init_lock=True,
                label="rightLowerArm",
                min=-60,
                max=60,
                data_index=20,
                is_related_same=False,
            ),
            "rightWrist": Servo(
                org="rightArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightWrist",
                min=-160,
                max=0,
                data_index=21,
                is_related_same=False,
            ),
            # "leftScapula": Servo(
            #     org="leftArm",
            #     init_value=0,
            #     first_value=0,
            #     init_lock=True,
            #     label="leftScapula",
            #     min=-95,
            #     max=0,
            #     data_index=10,
            #     is_related_same=False,
            # ),
            "leftShoulder": Servo(
                org="leftArm",
                init_value=0,
                first_value=-15,
                init_lock=True,
                label="leftShoulder",
                min=-180,
                max=40,
                data_index=11,
                is_related_same=False,
            ),
            "leftArm": Servo(
                org="leftArm",
                init_value=0,
                first_value=-15,
                init_lock=True,
                label="leftUpperArm",
                min=-60,
                max=5,
                data_index=12,
                is_related_same=False,
            ),
            "leftUpperArm": Servo(
                org="leftArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftElbow",
                min=-100,
                max=100,
                data_index=13,
                is_related_same=False,
            ),
            "leftElbow": Servo(
                org="leftArm",
                init_value=0,
                first_value=-30,
                init_lock=True,
                label="leftLowerArm",
                min=-60,
                max=60,
                data_index=14,
                is_related_same=False,
            ),
            "leftWrist": Servo(
                org="leftArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftWrist",
                min=0,
                max=160,
                data_index=15,
                is_related_same=False,
            ),
            # "waist": Servo(
            #     org="body",
            #     init_value=0,
            #     first_value=0,
            #     init_lock=True,
            #     label="waist",
            #     min=-185,
            #     max=30,
            #     data_index=22,
            #     is_related_same=False,
            # ),
            # "abdomen": Servo(
            #     org="body",
            #     init_value=0,
            #     first_value=0,
            #     init_lock=True,
            #     label="abdomen",
            #     min=-15,
            #     max=95,
            #     data_index=23,
            # ),
            "head": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="head",
                min=0,
                max=105,
                data_index=24,
            ),
            "rightWheelSpeed": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=False,
                label="rightWheelSpeed",
                min=-100,
                max=100,
                data_index=26,
                locked=True,
                is_related_same=False,
            ),
            "leftWheelSpeed": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=False,
                label="leftWheelSpeed",
                min=-100,
                max=100,
                data_index=25,
                locked=True,
                is_related_same=False,
            ),
        }

@dataclass
class Megatron(RobotState):
    def __post_init__(self):
        self.data = {
            "rightHip": Servo(
                org="rightLeg",
                init_value=0,
                first_value=8,
                init_lock=True,
                label="rightHip",
                min=-10,
                max=40,
                data_index=5,
                is_related_same=False,
            ),
            "rightThigh": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightThigh",
                min=-95,
                max=95,
                data_index=6,
                is_related_same=False,
            ),
            "rightCalf": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightCalf",
                min=-30,
                max=95,
                data_index=7,
                is_related_same=False,
            ),
            "rightAnkle": Servo(
                org="rightLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightAnkle",
                min=-50,
                max=95,
                data_index=8,
                is_related_same=False,
            ),
            "rightFoot": Servo(
                org="rightLeg",
                init_value=0,
                first_value=-8,
                init_lock=True,
                label="rightFoot",
                min=-60,
                max=20,
                data_index=9,
                is_related_same=False,
            ),
            "leftHip": Servo(
                org="leftLeg",
                init_value=0,
                first_value=-8,
                init_lock=True,
                label="leftHip",
                min=-40,
                max=10,
                data_index=0,
                is_related_same=False,
            ),
            "leftThigh": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftThigh",
                min=-95,
                max=95,
                data_index=1,
                is_related_same=False,
            ),
            "leftCalf": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftCalf",
                min=-95,
                max=30,
                data_index=2,
                is_related_same=False,
            ),
            "leftAnkle": Servo(
                org="leftLeg",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftAnkle",
                min=-95,
                max=50,
                data_index=3,
                is_related_same=False,
            ),
            "leftFoot": Servo(
                org="leftLeg",
                init_value=0,
                first_value=8,
                init_lock=True,
                label="leftFoot",
                min=-20,
                max=60,
                data_index=4,
                is_related_same=False,
            ),
            "rightScapula": Servo(
                org="rightArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightScapula",
                min=0,
                max=95,
                data_index=16,
                is_related_same=False,
            ),
            "rightShoulder": Servo(
                org="rightArm",
                init_value=0,
                first_value=15,
                init_lock=True,
                label="rightShoulder",
                min=-15,
                max=95,
                data_index=17,
                is_related_same=False,
            ),
            "rightUpperArm": Servo(
                org="rightArm",
                init_value=0,
                first_value=15,
                init_lock=True,
                label="rightUpperArm",
                min=-185,
                max=30,
                data_index=18,
                is_related_same=False,
            ),
            "rightElbow": Servo(
                org="rightArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightElbow",
                min=-95,
                max=95,
                data_index=19,
                is_related_same=False,
            ),
            "rightForeArm": Servo(
                org="rightArm",
                init_value=0,
                first_value=30,
                init_lock=True,
                label="rightForeArm",
                min=-60,
                max=95,
                data_index=20,
                is_related_same=False,
            ),
            "rightWrist": Servo(
                org="rightArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="rightWrist",
                min=-185,
                max=30,
                data_index=21,
                is_related_same=False,
            ),
            "leftScapula": Servo(
                org="leftArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftScapula",
                min=-95,
                max=0,
                data_index=10,
                is_related_same=False,
            ),
            "leftShoulder": Servo(
                org="leftArm",
                init_value=0,
                first_value=-15,
                init_lock=True,
                label="leftShoulder",
                min=-95,
                max=15,
                data_index=11,
                is_related_same=False,
            ),
            "leftRearArm": Servo(
                org="leftArm",
                init_value=0,
                first_value=-15,
                init_lock=True,
                label="leftRearArm",
                min=-30,
                max=185,
                data_index=12,
                is_related_same=False,
            ),
            "leftElbow": Servo(
                org="leftArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftElbow",
                min=-95,
                max=95,
                data_index=13,
                is_related_same=False,
            ),
            "leftForeArm": Servo(
                org="leftArm",
                init_value=0,
                first_value=-30,
                init_lock=True,
                label="leftForeArm",
                min=-95,
                max=60,
                data_index=14,
                is_related_same=False,
            ),
            "leftWrist": Servo(
                org="leftArm",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="leftWrist",
                min=-30,
                max=185,
                data_index=15,
                is_related_same=False,
            ),
            "waist": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="waist",
                min=-185,
                max=30,
                data_index=22,
                is_related_same=False,
            ),
            "abdomen": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="abdomen",
                min=-15,
                max=95,
                data_index=23,
            ),
            "head": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=True,
                label="head",
                min=0,
                max=105,
                data_index=24,
            ),
            "rightWheelSpeed": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=False,
                label="rightWheelSpeed",
                min=-100,
                max=100,
                data_index=26,
                locked=True,
                is_related_same=False,
            ),
            "leftWheelSpeed": Servo(
                org="body",
                init_value=0,
                first_value=0,
                init_lock=False,
                label="leftWheelSpeed",
                min=-100,
                max=100,
                data_index=25,
                locked=True,
                is_related_same=False,
            ),
        }

