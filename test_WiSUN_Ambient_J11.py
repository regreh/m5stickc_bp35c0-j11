from m5stack import *
import machine
import gc
import utime
import ure
import uos
import _thread
import wifiCfg
import ntptime
import wisun_udp
import binascii

# 固定値
GET_COEFFICIENT         = b'\x10\x81\x00\x01\x05\xFF\x01\x02\x88\x01\x62\x01\xD3\x00'           #D3     *積算電力量係数の要求
GET_TOTAL_POWER_UNIT    = b'\x10\x81\x00\x01\x05\xFF\x01\x02\x88\x01\x62\x01\xE1\x00'           #E1     *積算電力量単位の要求
GET_NOW_PA              = b'\x10\x81\x00\x01\x05\xFF\x01\x02\x88\x01\x62\x02\xE7\x00\xE8\x00'   #E7&E8  *瞬時電力計測値＆瞬時電流計測値（T/R相）の要求
GET_NOW_P               = b'\x10\x81\x00\x01\x05\xFF\x01\x02\x88\x01\x62\x01\xE7\x00'           #E7     *瞬時電力計測値の要求
GET_TOTAL_POWER_30      = b'\x10\x81\x00\x01\x05\xFF\x01\x02\x88\x01\x62\x01\xEA\x00'           #EA     *30分毎更新の積算電力量の要求

# 変数宣言
SCAN_COUNT              = 6     # ActiveScan count
channel                 = ''
panid                   = ''
macadr                  = ''
lqi                     = ''

Am_err                  = 1     # グローバル Ambientの初回通信が通るまでは時計は赤文字
Disp_mode               = 0     # グローバル
lcd_mute                = False # グローバル
data_mute               = False # グローバル
np_interval             = 5     # 瞬間電力値の要求サイクル（秒）※最短でも5秒以上が望ましい（基本は10秒とする）
am_interval             = 30    # Ambientへデータを送るサイクル（秒））※Ambientは3000件/日までなので、丸1日分持たせるには30秒以上にする

AM_ID_1                 = None  # Ambient設定が不備の場合
AM_WKEY_1               = None  # Ambient設定が不備の場合
AM_ID_2                 = None  # Ambient設定が不備の場合
AM_WKEY_2               = None  # Ambient設定が不備の場合
ESP_NOW_F               = False # ESP_NOWを使うかの設定値のデフォルト値
TIMEOUT                 = 30    # 何らかの事情で更新が止まった時のタイムアウト（秒）のデフォルト値
WDTIMEOUT               = 120   # 再起動タイムアウト（秒）のデフォルト値
AMPERE_RED              = 0.7   # 契約ブレーカー値に対し、どれくらいの使用率で赤文字化させるかのデフォルト値 （力率は無視してます）
AMPERE_LIMIT            = 30    # 契約ブレーカー値のデフォルト値

lcd_brightness = 2.65


# @cinimlさんのファーム差分吸収ロジック
class AXPCompat(object):
    def __init__(self):
        if( hasattr(axp, 'setLDO2Vol') ):
            self.setLDO2Vol = axp.setLDO2Vol
        else:
            self.setLDO2Vol = axp.setLDO2Volt

axp = AXPCompat()


# 時計表示スレッド関数
def time_count ():
    global Disp_mode
    global Am_err
    
    while True:
        if Am_err == 0 : # Ambient通信不具合発生時は時計の文字が赤くなる
            fc = lcd.WHITE
        else :
            fc = lcd.RED

        if Disp_mode == 1 : # 表示回転処理
            lcd.rect(67, 0, 80, 160, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DefaultSmall, rotate = 90)
            lcd.print('{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(*time.localtime()[:6]), 78, 40, fc)
        else :
            lcd.rect(0 , 0, 13, 160, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DefaultSmall, rotate = 270)
            lcd.print('{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(*time.localtime()[:6]), 2, 125, fc)
		
        utime.sleep(1)


# 表示OFFボタン処理スレッド関数
def buttonA_wasPressed():
    global lcd_mute

    if lcd_mute :
        lcd_mute = False
    else :
        lcd_mute = True

    if lcd_mute == True :
        axp.setLDO2Vol(0)   #バックライト輝度調整（OFF）
    else :
        axp.setLDO2Vol(lcd_brightness) #バックライト輝度調整（中くらい）


# 表示切替ボタン処理スレッド関数
def buttonB_wasPressed():
    global Disp_mode

    if Disp_mode == 1 :
        Disp_mode = 0
    else :
        Disp_mode = 1
    
    draw_lcd()


# 表示モード切替時の枠描画処理関数
def draw_lcd():
    global Disp_mode

    lcd.clear()

    if Disp_mode == 1 :
        lcd.line(66, 0, 66, 160, lcd.LIGHTGREY)
    else :
        lcd.line(14, 0, 14, 160, lcd.LIGHTGREY)
    
    draw_w()


# 瞬間電力値表示処理関数
def draw_w():
    global Disp_mode
    global lcd_mute
    global data_mute
    global AMPERE_LIMIT
    global AMPERE_RED

    if data_mute or (u.instant_power[0] == 0) : # タイムアウトで表示ミュートされてるか、初期値のままなら電力値非表示（黒文字化）
        fc = lcd.BLACK
    else :
        if u.instant_power[0] >= (AMPERE_LIMIT * AMPERE_RED * 100) :  # 警告閾値超え時は文字が赤くなる
            fc = lcd.RED
            if lcd_mute == True :   # 閾値超え時はLCD ON
                axp.setLDO2Vol(lcd_brightness) # バックライト輝度調整（中くらい）
        else :
            fc = lcd.WHITE
            if lcd_mute == True :
                axp.setLDO2Vol(0)   # バックライト輝度調整（オフ）
	
    if Disp_mode == 1 : # 表示回転処理
        lcd.rect(0, 0, 65, 160, lcd.BLACK, lcd.BLACK)
        lcd.font(lcd.FONT_DejaVu18, rotate = 90) # 単位(W)の表示
        lcd.print('W', 35, 120, fc)
        lcd.font(lcd.FONT_DejaVu24, rotate = 90) # 瞬時電力値の表示
        lcd.print(str(u.instant_power[0]), 40, 135 - ((len(str(u.instant_power[0])))* 24), fc)
    else :
        lcd.rect(15 , 0, 80, 160, lcd.BLACK, lcd.BLACK)
        lcd.font(lcd.FONT_DejaVu18, rotate = 270) # 単位(W)の表示
        lcd.print('W', 45, 40, fc)
        lcd.font(lcd.FONT_DejaVu24, rotate = 270) # 瞬時電力値の表示
        lcd.print(str(u.instant_power[0]), 40, 25 + ((len(str(u.instant_power[0])))* 24), fc)
	

# wisun_set_m.txtの存在/中身チェック関数
def wisun_set_filechk():
    global AMPERE_LIMIT
    global AMPERE_RED
    global TIMEOUT
    global BRID
    global BRPSWD
    global AM_ID_1
    global AM_WKEY_1
    global AM_ID_2
    global AM_WKEY_2
    global ESP_NOW_F

    scanfile_flg = False
    for file_name in uos.listdir('/flash') :
        if file_name == 'wisun_set_m.txt' :
            scanfile_flg = True

    if scanfile_flg :
        print('>> found [wisun_set_m.txt] !')
        with open('/flash/wisun_set_m.txt' , 'r') as f :
            for file_line in f :
                filetxt = file_line.strip().split(':')
                if filetxt[0] == 'AMPERE_RED' :
                    if float(filetxt[1]) >= 0 and float(filetxt[1]) <= 1 :
                        AMPERE_RED = float(filetxt[1])
                        print('- AMPERE_RED: ' + str(AMPERE_RED))
                elif filetxt[0] == 'AMPERE_LIMIT' :
                    if int(filetxt[1]) >= 20 :
                        AMPERE_LIMIT = int(filetxt[1])
                        print('- AMPERE_LIMIT: ' + str(AMPERE_LIMIT))
                elif filetxt[0] == 'TIMEOUT' :
                    if int(filetxt[1]) > 0 :
                        TIMEOUT = int(filetxt[1])
                        print('- TIMEOUT: ' + str(TIMEOUT))
                elif filetxt[0] == 'BRID' :
                    BRID = str(filetxt[1])
                    print('- BRID: ' + str(BRID))
                elif filetxt[0] == 'BRPSWD' :
                    BRPSWD = str(filetxt[1])
                    print('- BRPSWD: ' + str(BRPSWD))
                elif filetxt[0] == 'AM_ID_1' :
                    AM_ID_1 = str(filetxt[1])
                    print('- AM_ID_1: ' + str(AM_ID_1))
                elif filetxt[0] == 'AM_WKEY_1' :
                    if len(filetxt[1]) == 16 :
                        AM_WKEY_1 = str(filetxt[1])
                        print('- AM_WKEY_1: ' + str(AM_WKEY_1))
                elif filetxt[0] == 'AM_ID_2' :
                    AM_ID_2 = str(filetxt[1])
                    print('- AM_ID_2: ' + str(AM_ID_2))
                elif filetxt[0] == 'AM_WKEY_2' :
                    if len(filetxt[1]) == 16 :
                        AM_WKEY_2 = str(filetxt[1])
                        print('- AM_WKEY_2: ' + str(AM_WKEY_2))
                elif filetxt[0] == 'ESP_NOW' :
                    if int(filetxt[1]) == 0 or int(filetxt[1]) == 1 :
                        ESP_NOW_F = int(filetxt[1])
                        print('- ESP_NOW: ' + str(ESP_NOW_F))
                        
        if len(BRID) == 32 and len(BRPSWD) == 12: # BルートIDとパスワードの桁数チェック（NGならプログラム停止）
            scanfile_flg = True
        else :
            print('>> [wisun_set_m.txt] Illegal!!')
            scanfile_flg = False
            
    else :
        print('>> no [wisun_set_m.txt] !')
    return scanfile_flg


# Wi-SUN_SCAN.txtの存在/中身チェック関数
def wisun_scan_filechk():
    global channel
    global panid
    global macadr
    global lqi

    scanfile_flg = False
    for file_name in uos.listdir('/flash') :
        if file_name == 'Wi-SUN_SCAN.txt' :
            scanfile_flg = True
    if scanfile_flg :
        print('>> found [Wi-SUN_SCAN.txt] !')
        with open('/flash/Wi-SUN_SCAN.txt' , 'r') as f :
            for file_line in f :
                filetxt = file_line.strip().split(':')
                if filetxt[0] == 'Channel' :
                    channel = filetxt[1]
                    print('- Channel: ' + channel)
                elif filetxt[0] == 'Pan_ID' :
                    panid = filetxt[1]
                    print('- Pan_ID: ' + panid)
                elif filetxt[0] == 'MAC_Addr' :
                    macadr = filetxt[1]
                    print('- MAC_Addr: ' + macadr)
                elif filetxt[0] == 'LQI' :
                    lqi = filetxt[1]
                    print('- LQI: ' + lqi)
                elif filetxt[0] == 'COEFFICIENT' :
                    u.power_coefficient = int(filetxt[1])
                    print('- COEFFICIENT: ' + str(u.power_coefficient))
                elif filetxt[0] == 'UNIT' :
                    u.power_unit = float(filetxt[1])
                    print('- UNIT: ' + str(u.power_unit))
        if len(channel) == 2 and len(panid) == 4 and len(macadr) == 16:
            scanfile_flg = True
            channel=int(channel)
            panid=binascii.unhexlify(panid)
            macadr=binascii.unhexlify(macadr)
        else :
            print('>> [Wi-SUN_SCAN.txt] Illegal!!')
            scanfile_flg = False
    else :
        print('>> no [Wi-SUN_SCAN.txt] !')
    return scanfile_flg

# J11特有の送受信処理
def withlen(data):
    length = len(data)
    return [ length>>8, length&0xff ] + data
class J11Read(object):
    readbuf = b''
    line = b''
    j11 = None
    def __init__(self, uart):
        self.readbuf = b''
        self.line = b''
        self.j11 = uart
    def readline(self):
        while True: # Wait response
            if self.j11.any() != 0 :
                jbuf = self.j11.read()
                if jbuf is not None:
                    self.readbuf = self.readbuf + jbuf
            if b'\xd0\xf9\xee\x5d' in self.readbuf:
                indent = self.readbuf.index(b'\xd0\xf9\xee\x5d')
                length = self.readbuf[indent+6]*256 + self.readbuf[indent+7] - 4
                if len(self.readbuf) >= indent+12+length:
                    self.line = self.readbuf[indent : indent+12+length]
                    self.readbuf = self.readbuf[indent+12+length : ]
                    return self.line
            utime.sleep(0.1)
    def retcomplete(self):
        if self.j11.any() != 0 :
            jbuf = self.j11.read()
            if jbuf is not None:
                self.readbuf = self.readbuf + jbuf
        if b'\xd0\xf9\xee\x5d' in self.readbuf:
            indent = self.readbuf.index(b'\xd0\xf9\xee\x5d')
            length = self.readbuf[indent+6]*256 + self.readbuf[indent+7] - 4
            if len(self.readbuf) >= indent+12+length:
                return True
        return False
    def retcmd(self):
        if b'\xd0\xf9\xee\x5d' in self.line:
            indent = self.line.index(b'\xd0\xf9\xee\x5d')
            return self.line[indent+4]*256 + self.line[indent+5]
        return -1
    def retdata(self):
        if b'\xd0\xf9\xee\x5d' in self.line:
            indent = self.line.index(b'\xd0\xf9\xee\x5d')
            len = self.line[indent+6]*256 + self.line[indent+7] - 4
            return self.line[indent+12 : indent+12+len]
        return b''
    def clearbuf(self):
        if self.j11.any() != 0 :
            self.j11.read()
        return 0
    def sendcmd(self, cmd, data):
        bin = [0xd0, 0xea, 0x83, 0xfc]
        bin = bin + [ cmd>>8, cmd&0xff ]
        length = 4 + len(data)
        bin = bin + [ length>>8, length&0xff ]
        sum = 0
        for b in bin:
            sum = (sum + int(b)) & 0xffff
        bin = bin + [ sum>>8, sum&0xff ]
        sum = 0
        for b in data:
            sum = (sum + int(b)) & 0xffff
        bin = bin + [ sum>>8, sum&0xff ]
        self.j11.write(bytes(bin + data))

# メインプログラムはここから（この上はプログラム内関数）


# 基本設定ファイル[wisun_set_m.txt]のチェック 無い場合は例外エラー吐いて終了する
if not wisun_set_filechk() :
    lcd.print('err!! Check [wisun_set_m.txt] and restart!!', 0, 0, lcd.WHITE)
    raise ValueError('err!! Check [wisun_set_m.txt] and restart!!')


# WiFi設定
wifiCfg.autoConnect(lcdShow=True)
wifiCfg.network.WLAN(wifiCfg.network.AP_IF).active(False)
lcd.clear()
lcd.print('*', 0, 0, lcd.WHITE)
print('>> WiFi init OK')


# UDPデータインスタンス生成
u = wisun_udp.udp_read()
print('>> UDP reader init OK')


# Ambientインスタンス生成
if (AM_ID_1 is not None) and (AM_WKEY_1 is not None) : # Ambient_1の設定情報があった場合
    import ambient
    am_now_power = ambient.Ambient(AM_ID_1, AM_WKEY_1)
    print('>> Ambient_1 init OK')
if (AM_ID_2 is not None) and (AM_WKEY_2 is not None) : # Ambient_2の設定情報があった場合
    import ambient
    am_total_power = ambient.Ambient(AM_ID_2, AM_WKEY_2)
    print('>> Ambient_2 init OK')
lcd.print('**', 0, 0, lcd.WHITE)


# BP35C0-J11 UART設定
uart = machine.UART(1, tx=0, rx=36) # Wi-SUN HAT rev0.1用
#uart = machine.UART(1, tx=0, rx=26)
uart.init(115200, bits=8, parity=None, stop=1, timeout=50)
lcd.print('***', 0, 0, lcd.WHITE)
print('>> UART init OK')

buf = J11Read(uart)

# UARTの送受信バッファーの塵データをクリア
buf.clearbuf()
print('>> UART RX/TX Data Clear!')

# BP35C0-J11の初期設定 - RESETNピンにLowを入力 + ハードウェアリセットコマンド発行

RESET_TRIG = machine.Pin(26,machine.Pin.OUT)
RESET_TRIG.value(0)
utime.sleep(0.1)
RESET_TRIG.value(1)

buf.sendcmd(0x00d9, [])
utime.sleep(0.1)
while True: # Wait response
    buf.readline()
    if buf.retcmd() == 0x6019:
        break
print('>> BP35C0-J11 Echo back ON set OK')

lcd.print('****', 0, 0, lcd.WHITE)

# BP35C0-J11の初期設定
buf.sendcmd(0x005f, [0x05, 0x00, 0x04, 0x00])
while True: # Wait response
    buf.readline()
    if buf.retcmd() == 0x205f:
        if buf.retdata()[0] == 0x1:
            break

print('>> Initialize OK')
lcd.print('*****', 0, 0, lcd.WHITE)

# B-root ID+PASSWORDを送信
buf.sendcmd(0x0054, list(bytearray(BRID + BRPSWD)))

while True: # Wait response
    buf.readline()
    if buf.retcmd() == 0x2054:
        if buf.retdata()[0]==0x01:
            break
        else:
            print('!! BP35C0-J11 B-root ID and PASSWORD set NG')
            utime.sleep(3.0)
            buf.sendcmd(0x0054, list(bytearray(BRID + BRPSWD)))

print('>> BP35C0-J11 B-root ID and PASSWORD set OK')
lcd.print('***** **', 0, 0, lcd.WHITE)

gc.collect()

# Wi-SUNチャンネルスキャン（「Wi-SUN_SCAN.txt」の存在しない or 中身が異常値だった場合）
if not wisun_scan_filechk() :
#if True:
    #<Channel Scan>
    scanOK = False   
    print('>> Activescan start!')
    while not scanOK :
        SCAN_COUNT=0
        buf.sendcmd(0x0051,[0x06,0x00,0x03,0xFF,0xF0,0x01] + list(bytearray(BRID[-8:])))

        #スキャン1回分のループ処理
        scanEnd = False
        while not scanEnd :
            buf.readline()
            if buf.retcmd() == 0x2051:
                    scanEnd = True
                    print(">> Activescan done")
            if buf.retcmd() == 0x4051:
                    data = buf.retdata()
                    if data[0] == 0x00:
                        channel = data[1]
                        count = data[2]
                        macadr = data[3:11]
                        panid = data[11:13]
                        lqi = data[13]
                        scanOK=True
                        scanEnd=True
                        with open('/flash/Wi-SUN_SCAN.txt' , 'w') as f:
                            f.write('Channel:' + '{:02d}'.format(channel) + '\r\n')
                            f.write('Pan_ID:' + binascii.hexlify(panid).decode('utf-8') + '\r\n')
                            f.write('MAC_Addr:' + binascii.hexlify(macadr).decode('utf-8') + '\r\n')
                            f.write('LQI:' + str(lqi) + '\r\n')
                            print('>> [Wi-SUN_SCAN.txt] wrote!!')

                        print('Scan All Clear!')
                        scanOK = True
                    if data[0] == 0x01:
                        channel = data[1]
                        print("No response from Channel " + str(channel))
                        lcd.print(str(channel) + '-', (channel-4)//8*32, (channel-4)%8*16+32, lcd.BLUE)
        SCAN_COUNT+=1
        if SCAN_COUNT > 10 :
            raise ValueError('Scan retry count over! Please Reboot!')
lcd.print('***** ***', 0, 0, lcd.WHITE)

# PANA接続処理

####
buf.sendcmd(0x005f, [0x05, 0x00, channel, 0x00])

while True: # Wait response
    buf.readline()
    if buf.retcmd() == 0x205f:
            if buf.retdata()[0]==0x01:
                break
####
print(">> Initialize ok with channel " + str(channel))

buf.sendcmd(0x0053, [])
utime.sleep(0.5)

while True: # Wait response
    buf.readline()
    if buf.retcmd() == 0x2053:
        if buf.retdata()[0]==0x01:
                break
        elif buf.retdata()[0]==0x0e:
                print(">> No response from smartmeter")
                buf.sendcmd(0x0053, [])
                utime.sleep(0.5)
        else:
                print("!! 0x0053 FAILED with error code "+str(buf.retdata()[0]))
    else:
        print(">> Unknown response "+str(buf.retcmd()))
print(">> B-root connected")

buf.sendcmd(0x0005, [0x0e, 0x1a])
while True: # Wait response
    buf.readline()
    if buf.retcmd() == 0x2005:
            if buf.retdata()[0]==0x01:
                break
print(">> UDP port 0x0e1a opened")

buf.sendcmd(0x0056, [])
while True: # Wait response
    buf.readline()
    if buf.retcmd() == 0x2056:
            if buf.retdata()[0]==0x01:
                break
            elif buf.retdata()[0]==0x01:
                print(">> No response from smartmeter")
                utime.sleep(0.5)
                buf.sendcmd(0x0056, [])
    elif buf.retcmd() == 0x6028:
            if buf.retdata()[0]==0x01:
                print(">> PANA authentication OK!")
                break
            else:
                print(">> PANA authentication NG!  ...scan retry")
                utime.sleep(1)
                for file_name in uos.listdir('/flash') :
                    if file_name == 'Wi-SUN_SCAN.txt' :
                        uos.remove('/flash/Wi-SUN_SCAN.txt') #チャンネルが変わった可能性があるので、ファイル削除
                        scanfile_flg = False
                        channel = ''
                        panid = ''
                        macadr = ''
                        u.power_coefficient = 0
                        u.power_unit = 0.0
                break
    if buf.retcmd() == 0x6018:
            break

print(">> F19 received")

iph=[0xfe, 0x80, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
ipl=list(macadr)
ipl[0] = ipl[0] ^ 0x02
port=[0x0e, 0x1a, 0x0e, 0x1a]
payload = withlen(list(bytearray(GET_COEFFICIENT)))
buf.sendcmd(0x0008, iph+ipl+port+payload)

# ECHONET Lite 積算電力係数(COEFFICIENT)要求コマンド送信
while u.power_coefficient == 0: # Wait response
    buf.readline()
    if buf.retcmd() == 0x2008:
            if buf.retdata()[1]==0x00:
                continue
            elif buf.retdata()[1]==0x05:
                print(">> No response from smartmeter")
                utime.sleep(1.0)
                buf.sendcmd(0x0008, iph+list(macadr)+port+payload)
            else:
                print(">> Fail to send GET_COEFFICIENT "+hex(buf.retdata()[1]))
                utime.sleep(1.0)
                buf.sendcmd(0x0008, iph+list(macadr)+port+payload)
    elif buf.retcmd() == 0x6028:
            if retdata()[0]==0x01:
                print(">> PANA authentication OK!")
                continue
            else:
                print(">> PANA authentication failed with error code " + hex(buf.retdata()[0]))
                while True:
                    utime.sleep(1.0)
    elif buf.retcmd() == 0x6018:
        u.read('ERXUDP 1 2 3 4 5 6 7 ' + ''.join('{:02X}'.format(int(x)) for x in list(buf.retdata())[27:]))
        if u.type == 'D3' : #D3（積算電力量係数）受信待ち
            with open('/flash/Wi-SUN_SCAN.txt' , 'a') as fc:
                fc.write('COEFFICIENT:' + str(u.power_coefficient) + '\r\n')
        else:
            print(">> Unknown type "+u.type)
    else:
        print(">> Unknown response "+str(buf.retcmd()))
        buf.sendcmd(0x0008, iph+list(macadr)+port+payload)

gc.collect()
lcd.print('***** *****', 0, 0, lcd.WHITE)

payload = withlen(list(bytearray(GET_TOTAL_POWER_UNIT)))
buf.sendcmd(0x0008, iph+ipl+port+payload)

# ECHONET Lite 積算電力単位(UNIT)要求コマンド送信
while u.power_unit == 0.0 :
    buf.readline()
    if buf.retcmd() == 0x2008:
            if buf.retdata()[1]==0x00:
                print(">> 0x2008")
                continue
            elif buf.retdata()[1]==0x05:
                print(">> No response from smartmeter")
                utime.sleep(1.0)
                buf.sendcmd(0x0008, iph+list(macadr)+port+payload)
            else:
                print(">> Fail to send GET_COEFFICIENT "+hex(buf.retdata()[1]))
                utime.sleep(1.0)
                buf.sendcmd(0x0008, iph+list(macadr)+port+payload)
    elif buf.retcmd() == 0x6028:
            if buf.retdata()[0]==0x01:
                print(">> PANA authentication OK!")
                continue
            else:
                print(">> PANA authentication failed with error code " + hex(buf.retdata()[0]))
                while True:
                    utime.sleep(1.0)
    elif buf.retcmd() == 0x6018:
        u.read('ERXUDP 1 2 3 4 5 6 7 ' + ''.join('{:02X}'.format(int(x)) for x in list(buf.retdata())[27:]))
        if u.type == 'E1' : #E1（積算電力量単位）受信待ち
            with open('/flash/Wi-SUN_SCAN.txt' , 'a') as fu:
                fu.write('UNIT:' + str(u.power_unit) + '\r\n')
        else:
            print(">> Unknown type "+u.type)

    else:
        print(">> Unknown response "+str(buf.retcmd()))
        buf.sendcmd(0x0008, iph+list(macadr)+port+payload)

gc.collect()
lcd.print('***** ***** *', 0, 0, lcd.WHITE)

# ESP NOW設定
if ESP_NOW_F :
    import espnow
    espnow.init()
    print('>> ESP NOW init')
lcd.print('***** ***** **', 0, 0, lcd.WHITE)


print('heapmemory= ' + str(gc.mem_free()))


# RTC設定
utime.localtime(ntptime.settime())
print('>> RTC init OK')


# 画面初期化
axp.setLDO2Vol(lcd_brightness) #バックライト輝度調整（中くらい）
draw_lcd()
print('>> Disp init OK')


# 時刻表示スレッド起動
_thread.start_new_thread(time_count , ())
print('>> Time Count thread ON')


# ボタン検出スレッド起動
btnA.wasPressed(buttonA_wasPressed)
btnB.wasPressed(buttonB_wasPressed)
print('>> Button Check thread ON')


# タイムカウンタ初期値設定
np_c = utime.time()
tp_c = utime.time()
am_c = utime.time()
tp_f = False    # 積算電力量応答の有無フラグ


# メインループ

while True:
    if buf.retcomplete():
        buf.readline()
        if buf.retcmd() == 0x6018:
            u.read('ERXUDP 1 2 3 4 5 6 7 ' + ''.join('{:02X}'.format(int(x)) for x in list(buf.retdata())[27:]))
            if u.type == 'E7' :  # [E7]なら受信データは瞬時電力計測値
                data_mute = False
                draw_w()
                if ESP_NOW_F : # ESP NOW一斉同報発信を使う場合
                    espnow.broadcast(data=str('NPD=' + str(u.instant_power[0])))
                if (utime.time() - am_c) >= am_interval :
                    if (AM_ID_1 is not None) and (AM_WKEY_1 is not None) :  # Ambient_1が設定されてる場合
                        try :                                               # ネットワーク不通発生などで例外エラー終了されない様に try except しとく
                            rn = am_now_power.send({'d1': u.instant_power[0]})
                            print('Ambient send OK!  / ' + str(rn.status_code) + ' / ' + str(Am_err))
                            Am_err = 0
                            am_c = utime.time()
                            rn.close()
                        except :
                            print('Ambient send ERR! / ' + str(Am_err))
                            Am_err = Am_err + 1
            elif u.type == 'EA72' : # [EA72]なら受信データは積算電力量
                tp_f = True
                if ESP_NOW_F : # ESP NOW一斉同報発信を使う場合
                    espnow.broadcast(data=str('TPD=' + str(u.total_power[0]) + '/' + u.total_power[1]))
                if (AM_ID_2 is not None) and (AM_WKEY_2 is not None) :  # Ambient_2が設定されてる場合
                    try :                                               # ネットワーク不通発生などで例外エラー終了されない様に try except しとく
                        rt = am_total_power.send({'created': u.total_power[1], 'd1': u.total_power[0]})
                        print('Ambient send OK! (Total Power) / ' + str(rt.status_code) + ' / ' + str(Am_err))
                        Am_err = 0
                        rt.close()
                    except :
                        print('Ambient send ERR! (Total Power) / ' + str(Am_err))
                        Am_err = Am_err + 1
        elif buf.retcmd() == 0x6028:
            if buf.retdata()[0]==0x01:
                print(">> PANA authentication OK!")
                continue
            else:
                print(">> PANA authentication failed with error code " + hex(buf.retdata()[0]))
                while True:
                    utime.sleep(1.0)
        elif buf.retcmd() == 0x2008:
            continue
        elif buf.retcmd() == 0x6028:
            if buf.retdata()[0]!=0x01:
                print('>> No response for PANA authentication. Restart system...')
                machine.deepsleep(1)
        else:
            print(">> Unknown response "+hex(buf.retcmd())+str([hex(x) for x in buf.retdata()]))

    if ((utime.time() - tp_c) >= (30 * 60)) or ((not tp_f) and ((utime.time() - tp_c) >= 10)) : # 30分毎に積算電力量要求コマンド送信（受信出来ない時のコマンド再送信は10秒開ける）
        payload = withlen(list(bytearray(GET_TOTAL_POWER_30)))
        buf.sendcmd(0x0008, iph+ipl+port+payload)
        print('>> [GET_TOTAL_POWER_30] cmd send')
        tp_c = utime.time()
        tp_f = False
    elif (utime.time() - np_c) >= np_interval : # 瞬時電力計測値要求コマンド送信（コマンド頻度が多くなるので、受信できない時のコマンド再送信処理は無し）
        payload = withlen(list(bytearray(GET_NOW_P)))
        buf.sendcmd(0x0008, iph+ipl+port+payload)
        print('>> [GET_NOW_P] cmd send')
        np_c = utime.time()

    if not u.instant_power[1] == '' :
        if (utime.time() - u.instant_power[1]) >= TIMEOUT : # スマートメーターから瞬時電力計測値の応答が一定時間無い場合は電力値表示のみオフ
            data_mute = True
            draw_w()
        if (utime.time() - u.instant_power[1]) >= WDTIMEOUT : # スマートメーターから瞬時電力計測値の応答が長時間無い場合はM5StickCをリセット
            print('>> No response for a while. Restart system...')
            machine.deepsleep(1)

    utime.sleep(0.1)
    gc.collect()
    
