import importlib.util
from pathlib import Path
import os,socket,tempfile,unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('keyboard_server',Path(__file__).resolve().parents[1]/'scripts'/'keyboard-server.py')
keyboard=importlib.util.module_from_spec(spec);spec.loader.exec_module(keyboard)

class PrivateKeyboardTests(unittest.TestCase):
    def test_private_peer_keeps_session_bus_and_clears_phone_policy(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'XDG_RUNTIME_DIR':root,'DBUS_SESSION_BUS_ADDRESS':'phone-session','LD_PRELOAD':'phone-policy','QT_WAYLAND_SHELL_INTEGRATION':'unsupported-plugin'}),patch.object(keyboard.os,'execve') as execute:
            keyboard.main()
            binary,args,env=execute.call_args.args
            self.assertEqual(binary,'/usr/bin/maliit-server')
            self.assertEqual(args[-1],'unix:path='+root+'/sailplay-maliit/socket')
            self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'],'phone-session')
            self.assertEqual(env['MALIIT_FORCE_DBUS_CONNECTION'],'1')
            self.assertEqual(env['WAYLAND_DISPLAY'],'imira-comp-0')
            self.assertEqual(env['CARLIFE_APP_KEY'],'sailplay-input-method')
            self.assertNotIn('LD_PRELOAD',env)
            self.assertNotIn('QT_WAYLAND_SHELL_INTEGRATION',env)
            self.assertEqual((Path(root)/'sailplay-maliit').stat().st_mode & 0o777,0o700)
            record=Path(root)/('sailplay-app-'+str(os.getpid()))
            fields=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
            self.assertEqual(record.read_text().splitlines(),['sailplay-input-method',fields[19]])
            self.assertEqual(record.stat().st_mode & 0o777,0o600)

    def test_live_peer_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'XDG_RUNTIME_DIR':root}),patch.object(keyboard.os,'execve') as execute:
            directory=Path(root)/'sailplay-maliit';directory.mkdir()
            server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            try:
                server.bind(str(directory/'socket'));server.listen(1)
                with self.assertRaisesRegex(RuntimeError,'already running'):keyboard.main()
                self.assertTrue((directory/'socket').exists());execute.assert_not_called()
            finally:server.close()

    def test_stale_owned_socket_is_cleaned_but_regular_file_is_not(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'XDG_RUNTIME_DIR':root}),patch.object(keyboard.os,'execve'):
            directory=Path(root)/'sailplay-maliit';directory.mkdir();path=directory/'socket'
            server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));server.close()
            keyboard.main();self.assertFalse(path.exists())
            path.write_text('preserve')
            with self.assertRaisesRegex(RuntimeError,'unsafe keyboard socket'):keyboard.main()
            self.assertEqual(path.read_text(),'preserve')
