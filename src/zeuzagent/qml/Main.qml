import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    width: 1100
    height: 720
    minimumWidth: 900
    minimumHeight: 620
    visible: true
    color: "#09101A"
    title: "Zeuz Agent"

    property color surface: "#111B28"
    property color raised: "#172536"
    property color border: "#263A50"
    property color primary: "#20B8D8"
    property color primaryDark: "#07141B"
    property color textMain: "#F4F8FC"
    property color textMuted: "#91A4B8"
    property color success: "#45D497"
    property color warning: "#F1B955"
    property color danger: "#FF647D"

    onClosing: function(close) {
        if (backend.trayAvailable && !backend.quitting) {
            close.accepted = false
            window.hide()
            backend.notifyStillRunning()
        }
    }

    component Card: Rectangle {
        radius: 18
        color: window.surface
        border.color: window.border
        border.width: 1
    }

    component ZeuzButton: Button {
        id: control
        property color buttonColor: window.primary
        property color labelColor: window.primaryDark
        implicitHeight: 44
        leftPadding: 18
        rightPadding: 18
        font.pixelSize: 14
        font.weight: Font.DemiBold
        background: Rectangle {
            radius: 11
            color: !control.enabled ? "#263341"
                  : control.down ? Qt.darker(control.buttonColor, 1.18)
                  : control.hovered ? Qt.lighter(control.buttonColor, 1.08)
                  : control.buttonColor
        }
        contentItem: Text {
            text: control.text
            color: control.enabled ? control.labelColor : "#778899"
            font: control.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    component SectionTitle: Text {
        color: window.textMuted
        font.pixelSize: 12
        font.weight: Font.Bold
        font.letterSpacing: 1.2
    }

    header: Rectangle {
        height: 76
        color: "#0C1521"
        border.color: window.border
        border.width: 0

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 26
            anchors.rightMargin: 26
            spacing: 16

            Rectangle {
                Layout.preferredWidth: 44
                Layout.preferredHeight: 44
                radius: 12
                color: primary
                Text {
                    anchors.centerIn: parent
                    text: "Z"
                    color: primaryDark
                    font.pixelSize: 25
                    font.weight: Font.Black
                }
            }

            ColumnLayout {
                spacing: 1
                Text {
                    text: "ZEUZ AGENT"
                    color: textMain
                    font.pixelSize: 20
                    font.weight: Font.Black
                    font.letterSpacing: 1.1
                }
                Text {
                    text: "Puente local de programas CNC"
                    color: textMuted
                    font.pixelSize: 12
                }
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                Layout.preferredWidth: statusRow.implicitWidth + 24
                Layout.preferredHeight: 38
                radius: 19
                color: backend.running ? "#15382F" : backend.error ? "#41212B" : "#252F3B"
                border.color: backend.running ? "#2C6B58" : backend.error ? "#744052" : "#39495A"
                Row {
                    id: statusRow
                    anchors.centerIn: parent
                    spacing: 8
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 9
                        height: 9
                        radius: 5
                        color: backend.running ? success : backend.error ? danger : textMuted
                    }
                    Text {
                        text: backend.status.toUpperCase()
                        color: backend.running ? success : backend.error ? danger : textMuted
                        font.pixelSize: 12
                        font.weight: Font.Bold
                    }
                }
            }

            ZeuzButton {
                text: backend.running ? "DETENER" : "INICIAR"
                buttonColor: backend.running ? "#3B2830" : primary
                labelColor: backend.running ? danger : primaryDark
                onClicked: backend.running ? backend.stop() : backend.start()
            }

            Button {
                text: "Salir"
                flat: true
                palette.buttonText: textMuted
                onClicked: backend.quitApplication()
            }
        }
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: 16

            Item { Layout.preferredHeight: 4 }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                spacing: 16

                Card {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 220

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10

                        SectionTitle { text: "EMPAREJAMIENTO" }
                        Text {
                            text: backend.pairingCode
                            color: textMain
                            font.pixelSize: 42
                            font.weight: Font.Black
                            font.letterSpacing: 7
                        }
                        Text {
                            text: "Introduce este código en ZeuzDNC para autorizar el dispositivo."
                            color: textMuted
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        Item { Layout.fillHeight: true }
                        RowLayout {
                            Layout.fillWidth: true
                            ZeuzButton {
                                text: "COPIAR CÓDIGO"
                                onClicked: backend.copyText(backend.pairingCode.replace(" ", ""))
                            }
                            ZeuzButton {
                                text: "GENERAR OTRO"
                                buttonColor: raised
                                labelColor: textMain
                                onClicked: backend.regeneratePairingCode()
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                Card {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 220

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10

                        SectionTitle { text: "DIRECCIÓN DEL AGENTE" }
                        Repeater {
                            model: backend.addresses
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 48
                                radius: 11
                                color: raised
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 8
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.url
                                        color: textMain
                                        font.family: "Consolas"
                                        font.pixelSize: 14
                                        elide: Text.ElideRight
                                    }
                                    Button {
                                        text: "Copiar"
                                        flat: true
                                        palette.buttonText: primary
                                        onClicked: backend.copyText(modelData.url)
                                    }
                                }
                            }
                        }
                        Text {
                            text: backend.discoveryStatus
                            color: backend.running ? success : textMuted
                            font.pixelSize: 13
                        }
                        Text {
                            visible: backend.error.length > 0
                            text: backend.error
                            color: danger
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                Layout.preferredHeight: 128

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 10

                    SectionTitle { text: "CARPETA DE PROGRAMAS CNC" }
                    RowLayout {
                        Layout.fillWidth: true
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48
                            radius: 11
                            color: raised
                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                verticalAlignment: Text.AlignVCenter
                                text: backend.programsDir
                                color: textMain
                                font.pixelSize: 14
                                elide: Text.ElideMiddle
                            }
                        }
                        ZeuzButton {
                            text: "ABRIR"
                            buttonColor: raised
                            labelColor: textMain
                            onClicked: backend.openProgramsDirectory()
                        }
                        ZeuzButton {
                            text: "CAMBIAR"
                            onClicked: backend.selectProgramsDirectory()
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                Layout.bottomMargin: 22
                spacing: 16

                Card {
                    Layout.preferredWidth: 380
                    Layout.preferredHeight: 260

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 11

                        SectionTitle { text: "CONFIGURACIÓN" }
                        TextField {
                            id: nameField
                            Layout.fillWidth: true
                            implicitHeight: 44
                            text: backend.agentName
                            color: textMain
                            placeholderText: "Nombre del agente"
                            placeholderTextColor: textMuted
                            background: Rectangle {
                                radius: 10
                                color: raised
                                border.color: nameField.activeFocus ? primary : border
                            }
                        }
                        SpinBox {
                            id: portField
                            Layout.fillWidth: true
                            from: 1024
                            to: 65535
                            value: backend.port
                            editable: true
                            textFromValue: function(value, locale) {
                                return value.toString()
                            }
                            valueFromText: function(text, locale) {
                                return parseInt(text)
                            }
                            implicitHeight: 44
                        }
                        Switch {
                            text: "Iniciar con la computadora"
                            checked: backend.startsWithComputer
                            palette.windowText: textMain
                            onToggled: backend.setStartsWithComputer(checked)
                        }
                        Item { Layout.fillHeight: true }
                        RowLayout {
                            Layout.fillWidth: true
                            ZeuzButton {
                                text: "GUARDAR"
                                onClicked: backend.saveIdentity(nameField.text, portField.value)
                            }
                            ZeuzButton {
                                text: "REVOCAR ACCESOS"
                                buttonColor: "#3B2830"
                                labelColor: danger
                                onClicked: revokeDialog.open()
                            }
                        }
                    }
                }

                Card {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 260

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            SectionTitle {
                                Layout.fillWidth: true
                                text: "ACTIVIDAD RECIENTE"
                            }
                            Button {
                                text: "Limpiar"
                                flat: true
                                palette.buttonText: primary
                                onClicked: backend.clearActivity()
                            }
                        }

                        ListView {
                            id: activityList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 6
                            model: backend.activity
                            delegate: Rectangle {
                                required property var modelData
                                width: activityList.width
                                height: messageText.implicitHeight + 16
                                radius: 9
                                color: raised
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 9
                                    Text {
                                        text: modelData.time
                                        color: textMuted
                                        font.family: "Consolas"
                                        font.pixelSize: 11
                                    }
                                    Rectangle {
                                        Layout.preferredWidth: 7
                                        Layout.preferredHeight: 7
                                        radius: 4
                                        color: modelData.level === "error" ? danger
                                             : modelData.level === "warning" ? warning
                                             : success
                                    }
                                    Text {
                                        id: messageText
                                        Layout.fillWidth: true
                                        text: modelData.message
                                        color: textMain
                                        font.pixelSize: 12
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: revokeDialog
        anchors.centerIn: parent
        width: 460
        modal: true
        title: "Revocar todos los accesos"
        standardButtons: Dialog.Cancel | Dialog.Ok
        onAccepted: backend.revokeAllDevices()
        contentItem: Text {
            text: "Todos los iPhone, Raspberry y computadoras emparejados perderán acceso. Se generará un token y un código nuevos."
            color: textMain
            wrapMode: Text.Wrap
            padding: 16
        }
        background: Rectangle {
            radius: 16
            color: surface
            border.color: border
        }
    }

    footer: Rectangle {
        height: 30
        color: "#0C1521"
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            Text {
                text: backend.trayAvailable
                      ? "Cerrar la ventana mantiene el agente activo en la bandeja."
                      : "La bandeja del sistema no está disponible."
                color: textMuted
                font.pixelSize: 11
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "v" + backend.version
                color: textMuted
                font.pixelSize: 11
            }
        }
    }
}
