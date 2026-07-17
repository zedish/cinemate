# Makefile for wayfire-kiosk
SYSDDIR  ?= /etc/systemd/system
CONFIG   ?= /home/pi/.config
PI_USER  ?= pi

CONFIG_FILE   = wayfire.ini
SPLASH_PAGE   = splash.html
UDEV_RULE     = 99-goodix-hyperpixel-touch.rules
SERVICE       = cinemate-kiosk.service

.PHONY: all install enable disable start stop restart status clean uninstall

all:
	@echo "Nothing to build – use 'make install'"

install:
	install -m 644 $(CONFIG_FILE) $(CONFIG)/$(CONFIG_FILE)
	install -m 644 $(SPLASH_PAGE) $(CONFIG)/$(SPLASH_PAGE)
	install -m 644 $(SERVICE)     $(SYSDDIR)/$(SERVICE)
	install -m 644 $(UDEV_RULE)   /etc/udev/rules.d/$(UDEV_RULE)
	udevadm control --reload-rules
	systemctl daemon-reload
	@echo "Installed kiosk: config, splash page, udev rule, and service"

enable: install
	systemctl enable  $(SERVICE)

disable:
	- systemctl disable $(SERVICE)

start:
	systemctl start $(SERVICE)

stop:
	systemctl stop $(SERVICE)

restart:
	systemctl restart $(SERVICE)

status:
	systemctl status $(SERVICE)

clean: disable
	- rm -f $(CONFIG)/$(CONFIG_FILE)
	- rm -f $(CONFIG)/$(SPLASH_PAGE)
	- rm -f $(SYSDDIR)/$(SERVICE)
	- rm -f /etc/udev/rules.d/$(UDEV_RULE)
	udevadm control --reload-rules
	systemctl daemon-reload
	@echo "Removed kiosk files"

uninstall: clean
