# Chaquopy вызывает Java через JNI и рефлексию: его классы не трогаем (AAR несёт и свои правила)
-keep class com.chaquo.python.** { *; }

# commons-compress: необязательные форматы (xz, zstd, brotli) в приложении не используются
-dontwarn org.apache.commons.compress.**
-dontwarn com.github.luben.zstd.**
-dontwarn org.tukaani.xz.**
-dontwarn org.brotli.dec.**
-dontwarn com.google.errorprone.annotations.**

# Читаемые трассировки ошибок в журнале
-keepattributes SourceFile,LineNumberTable
