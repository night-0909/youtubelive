SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;


CREATE TABLE `chats` (
  `id_chat` int(11) NOT NULL,
  `id_live` int(11) NOT NULL,
  `filenumber` varchar(3) NOT NULL,
  `dateStart` datetime NOT NULL,
  `dateEnd` datetime DEFAULT NULL,
  `chat_pid` int(11) DEFAULT NULL,
  `status_chat` varchar(400) CHARACTER SET latin1 COLLATE latin1_swedish_ci DEFAULT NULL,
  `status_chat_downloader` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE `lives` (
  `id_live` int(11) NOT NULL,
  `idchannel` varchar(255) NOT NULL,
  `handlechannel` varchar(255) NOT NULL,
  `idVideo` varchar(255) NOT NULL,
  `title` text NOT NULL,
  `dateFirstStartRecord` datetime DEFAULT NULL,
  `dateFirstStartChat` datetime DEFAULT NULL,
  `dateLastEndRecord` datetime DEFAULT NULL,
  `dateLastEndChat` datetime DEFAULT NULL,
  `dateStart_YTB` datetime DEFAULT NULL,
  `dateEnd_YTB` datetime DEFAULT NULL,
  `status_merging_all` varchar(400) DEFAULT NULL,
  `status_merging_all_ffmpeg` int(11) DEFAULT NULL,
  `date_status_merging_all` datetime DEFAULT NULL,
  `status_merging_all_duration` varchar(5000) DEFAULT NULL,
  `status_merging_all_duration_ffprobe` int(11) DEFAULT NULL,
  `status_rename_chat` varchar(400) DEFAULT NULL,
  `status_downloading_all` varchar(400) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE `records` (
  `id_record` int(11) NOT NULL,
  `id_live` int(11) NOT NULL,
  `filenumber` varchar(3) NOT NULL,
  `dateStart` datetime NOT NULL,
  `dateEnd` datetime DEFAULT NULL,
  `recording_pid` int(11) DEFAULT NULL,
  `recording_live_tool` varchar(400) NOT NULL,
  `status_recording` varchar(400) DEFAULT NULL,
  `status_recording_record_live_tool` varchar(400) DEFAULT NULL,
  `status_recording_duration` varchar(5000) DEFAULT NULL,
  `status_recording_duration_ffprobe` int(11) DEFAULT NULL,
  `status_convert` varchar(400) DEFAULT NULL,
  `status_convert_ffmpeg` int(11) DEFAULT NULL,
  `date_status_convert` datetime DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;


ALTER TABLE `chats`
  ADD PRIMARY KEY (`id_chat`),
  ADD UNIQUE KEY `chats_unique_key` (`id_live`,`filenumber`) USING BTREE,
  ADD KEY `chats_id_live` (`id_chat`);

ALTER TABLE `lives`
  ADD PRIMARY KEY (`id_live`) USING BTREE,
  ADD UNIQUE KEY `idVideo` (`idVideo`),
  ADD KEY `lives_id_live` (`id_live`);

ALTER TABLE `records`
  ADD PRIMARY KEY (`id_record`),
  ADD UNIQUE KEY `lives_unique_key` (`id_live`,`filenumber`),
  ADD KEY `records_id_live` (`id_live`);


ALTER TABLE `chats`
  MODIFY `id_chat` int(11) NOT NULL AUTO_INCREMENT;

ALTER TABLE `lives`
  MODIFY `id_live` int(11) NOT NULL AUTO_INCREMENT;

ALTER TABLE `records`
  MODIFY `id_record` int(11) NOT NULL AUTO_INCREMENT;


ALTER TABLE `chats`
  ADD CONSTRAINT `chats_ibfk_1` FOREIGN KEY (`id_live`) REFERENCES `lives` (`id_live`) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `records`
  ADD CONSTRAINT `records_ibfk_1` FOREIGN KEY (`id_live`) REFERENCES `lives` (`id_live`) ON DELETE CASCADE ON UPDATE CASCADE;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
