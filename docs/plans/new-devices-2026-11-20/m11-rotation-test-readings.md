# m11 rotation reboot test: raw adb readings (2026-11-20)

Source: adb shell reads on HA2PMV18; no boot logcat included (it holds account data).

## 0-pre

```
up= 10:43:41 up 22:50, 0 users,
boot=1
accel=0 user=2 cam=1
wm: lock 2 
fixed: default 
ignoreOrient: ignoreOrientationRequest true for displayId=0 
      mCurrentRotation=ROTATION_180
        mDesiredRotation=ROTATION_180
    mUserRotationMode=USER_ROTATION_LOCKED mUserRotation=ROTATION_180 mCameraRotationMode=1 mAllowAllRotations=true
        RotationLockHistory
          11-19 11:56:42.979: mode=USER_ROTATION_LOCKED, rotation=ROTATION_0, caller=DisplayRotationReversionController#revertOverride

  InputConsumers:
    name=recents_animation_input_consumer pid=31241 user=UserHandle{0}

  WindowInsetsStateController
    mShowingDream=false mDreamingLockscreen=false
    isKeyguardShowing=false
```

## 1-applied

```
up= 10:43:44 up 22:50, 0 users,
boot=1
accel=0 user=0 cam=0
wm: lock 0 
fixed: enabled 
ignoreOrient: ignoreOrientationRequest true for displayId=0 
      mCurrentRotation=ROTATION_0
        mDesiredRotation=ROTATION_180
    mUserRotationMode=USER_ROTATION_LOCKED mUserRotation=ROTATION_0 mCameraRotationMode=0 mAllowAllRotations=true
        RotationLockHistory
          11-19 11:56:42.979: mode=USER_ROTATION_LOCKED, rotation=ROTATION_0, caller=DisplayRotationReversionController#revertOverride
          11-20 10:43:43.339: mode=USER_ROTATION_LOCKED, rotation=ROTATION_0, caller=WindowManagerShellCommand#lock

  InputConsumers:
    name=recents_animation_input_consumer pid=31241 user=UserHandle{0}

    mShowingDream=false mDreamingLockscreen=false
    isKeyguardShowing=false
```

## 2-boot-first

```
up= 10:44:56 up 0 min, 0 users,
boot=1
accel=0 user=0 cam=0
wm: lock 0 
fixed: enabled 
ignoreOrient: ignoreOrientationRequest true for displayId=0 
      mCurrentRotation=ROTATION_0
        mDesiredRotation=-1
    mUserRotationMode=USER_ROTATION_LOCKED mUserRotation=ROTATION_0 mCameraRotationMode=0 mAllowAllRotations=unknown
    mShowingDream=false mDreamingLockscreen=false
    isKeyguardShowing=true
```

## 3-boot-plus-25s

```
up= 10:45:26 up 1 min, 0 users,
boot=1
accel=0 user=0 cam=0
wm: lock 0 
fixed: enabled 
ignoreOrient: ignoreOrientationRequest false for displayId=0 
      mCurrentRotation=ROTATION_0
        mDesiredRotation=-1
    mUserRotationMode=USER_ROTATION_LOCKED mUserRotation=ROTATION_0 mCameraRotationMode=0 mAllowAllRotations=unknown
    mShowingDream=false mDreamingLockscreen=true
    isKeyguardShowing=true
```

## 3-boot-plus-60s

```
up= 10:45:34 up 1 min, 0 users,
boot=1
accel=0 user=0 cam=0
wm: lock 0 
fixed: enabled 
ignoreOrient: ignoreOrientationRequest false for displayId=0 
      mCurrentRotation=ROTATION_0
        mDesiredRotation=-1
    mUserRotationMode=USER_ROTATION_LOCKED mUserRotation=ROTATION_0 mCameraRotationMode=0 mAllowAllRotations=unknown
    mShowingDream=false mDreamingLockscreen=true
    isKeyguardShowing=true
```

## 4-boot-plus-2min

```
up= 10:46:01 up 1 min, 0 users,
boot=1
accel=0 user=0 cam=0
wm: lock 0 
fixed: enabled 
ignoreOrient: ignoreOrientationRequest false for displayId=0 
      mCurrentRotation=ROTATION_0
        mDesiredRotation=-1
    mUserRotationMode=USER_ROTATION_LOCKED mUserRotation=ROTATION_0 mCameraRotationMode=0 mAllowAllRotations=unknown
    mShowingDream=false mDreamingLockscreen=true
    isKeyguardShowing=true
```
