"""Select one validated SDK or legacy navigation provider for the vehicle."""
import base64
import os
import re

from sailplay_sdk.discovery import SERVICE_NAME
from sailplay_sdk.guidance import unsigned, validate_guidance
from sailplay_sdk.model import Fault

from .navigationadapter import organicmaps_snapshot
from .navigationfeed import NavigationFeed


class SdkNavigationFeed(NavigationFeed):
    prefix = 'sailplay-sdk-'
    executables = ('carui',)
    maximum_bytes = 65536

    def _validate(self, value, now_ms, boot_id, start_ticks, pid, process):
        if (not isinstance(value, dict) or type(value.get('schema')) is not int
                or value['schema'] != 2 or value.get('source') != 'sailplay-sdk'):
            raise ValueError('unsupported SDK navigation export')
        if value.get('pid') != pid or not unsigned(value.get('pid')):
            raise ValueError('SDK navigation publisher PID mismatch')
        if value.get('bootId') != boot_id or value.get('startTicks') != start_ticks:
            raise ValueError('SDK navigation publisher identity mismatch')
        if not unsigned(value.get('heartbeatMs')) or not 0 <= now_ms - value['heartbeatMs'] <= 3000:
            raise ValueError('expired SDK navigation publisher')
        if os.readlink(os.path.join(process, 'exe')) != '/opt/sailplay/carui/carui':
            raise ValueError('unrecognized SDK navigation publisher')
        with open(os.path.join(process, 'environ'), 'rb') as source:
            if b'WAYLAND_DISPLAY=imira-comp-0' not in source.read(65536).split(b'\0'):
                raise ValueError('SDK navigation publisher is outside projection')
        application_id = value.get('applicationId')
        service = value.get('service')
        instance = value.get('instanceId')
        sequence = value.get('sequence')
        if (not isinstance(application_id, str) or not application_id or len(application_id) > 255
                or '/' in application_id or '\0' in application_id):
            raise ValueError('invalid SDK navigation application identity')
        if value.get('appKey') != base64.b64encode(application_id.encode('utf-8')).decode('ascii'):
            raise ValueError('SDK navigation application key mismatch')
        if not isinstance(service, str) or len(service) > 255 or not SERVICE_NAME.fullmatch(service):
            raise ValueError('invalid SDK navigation service')
        if not isinstance(instance, str) or not instance or len(instance) > 128 or '\0' in instance:
            raise ValueError('invalid SDK navigation backend identity')
        if not isinstance(sequence, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', sequence):
            raise ValueError('invalid SDK navigation revision')
        if not unsigned(int(sequence)):
            raise ValueError('SDK navigation revision overflow')
        navigation = value.get('navigation')
        if not isinstance(navigation, dict):
            raise ValueError('invalid SDK navigation model')
        navigation = dict(navigation)
        seconds = navigation.get('remainingSeconds')
        if isinstance(seconds, str) and re.fullmatch(r'(?:0|[1-9][0-9]{0,19})', seconds):
            navigation['remainingSeconds'] = int(seconds)
        try:
            navigation = validate_guidance(navigation, now_ms)
        except Fault as error:
            raise ValueError(str(error))
        return dict(providerId=application_id, instanceId=instance, sequence=int(sequence), navigation=navigation)


class ProviderNavigationFeed:
    def __init__(self, runtime='/run/user/100000', uid=100000, proc='/proc', clock=None):
        self.legacy = NavigationFeed(runtime, uid, proc, clock)
        self.sdk = SdkNavigationFeed(runtime, uid, proc, clock)
        self.reason = 'absent'

    def poll(self):
        sdk, legacy = self.sdk.poll(), self.legacy.poll()
        if (sdk is not None and legacy is not None
                or 'ambiguous' in (self.sdk.reason, self.legacy.reason)):
            self.reason = 'ambiguous'
            return None
        if sdk is not None:
            self.reason = 'sdk-ready'
            return sdk
        if legacy is not None:
            self.reason = 'legacy-ready'
            return organicmaps_snapshot(legacy)
        self.reason = self.sdk.reason if self.sdk.reason != 'absent' else self.legacy.reason
        return None
