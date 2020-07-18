# 概要
[M5StickCで家庭用スマートメーターをハックする！](https://kitto-yakudatsu.com/archives/7206) をBP35C0-J11-T01でやってみました。

# BP35C0-J11について
BP35C0-J11-T01というのはローム社のBルート/Enhanced HAN対応無線モジュールBP35C0-J11を2.54mmピッチの基板に差せるようにしたものです。（シリーズ内のBP35C1-J11-T01はBP35A1と同じコネクタ？）
インターネット上の記事でよく使われるBP35A1と比較したBP35C0-J11の特徴は以下の通りです。

- Wi-SUN Enhanced HAN通信に対応
- **コマンド送受信がJ11-UART規格のバイナリ**（BP35A1はSKSTACK-IP用SKコマンド、テキストベース）

コマンド体系が変わることで大部分書き換える必要があったので公開してみました。

# 用意したもの
 
- BP35C0-J11-T01
- 外付けアンテナ
- M5StickC
- ブレッドボード

BP35C0-J11はアンテナ外付けが必要ですが、特定小電力無線なのでBP35C0-J11との組み合わせで技適対応が確認されたものを使用する必要があります。（[対応製品のリストはここに掲載されています](https://micro.rohm.com/jp/download_support/wi-sun/)）


# 結線
M5StickCとBP35C0-J11-T01を以下のように結線します。なおブレッドボードに直接差そうとするとCN3が邪魔なのでCN3のピンヘッダを外すか、ピンソケットで下駄をはかせる必要があります。

|M5StickC|BP35C0-J11-T01|
|:-:|:-:|
|GND|CN1-1 or 9(GND)|
|3V3|CN1-4 or 5(VCC)|
|G36|CN2-5(TXD)|
|G26|CN2-7(RESET)|
|G0 |CN2-4(RXD)|

![ブレッドボードでの実装例](https://qiita-image-store.s3.ap-northeast-1.amazonaws.com/0/494347/6ff7f267-245e-72d8-46b6-b94a57b445b2.jpeg) ![M5StickCとBP35C0-J11-T01を載せるとこんな感じ](https://qiita-image-store.s3.ap-northeast-1.amazonaws.com/0/494347/430f4204-b144-2387-b41f-3ae9d5732b13.jpeg)

# プログラム

[ソースはgithubに置いています。](https://github.com/regreh/m5stickc_bp35c0-j11)

[元のプログラム](https://github.com/rin-ofumi/m5stickc_wisun_hat)の手順のうちtest_WiSUN_Ambient.pyの代わりにtest_WiSUN_Ambient_J11.pyをアップロードします。
ESPNOW関連のコードは互換性があるのでモニター子機は元のプログラムのものがそのまま使えます。


## 考慮すべき点

- 応答が可変長バイナリなのでreadlineが使えない
- コマンド送信時にチェックサムを付与する必要がある
- readで読み取った内容に応答1文が完全に含まれているとは限らない、逆に2文以上の応答を受信しているかもしれない
- 数日動かしているとPANA再認証の通信に失敗し、スマートメーターと通信できなくなることがある → 自動再起動で対処
