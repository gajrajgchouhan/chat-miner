import logging
import re
import pandas as pd
from enum import Enum
from dateutil import parser as datetimeparser
from pathlib import Path
from abc import ABC, abstractmethod
logging.basicConfig(level=logging.INFO)


class Parser(ABC):
    def __init__(self, filepath):
        self._file = Path(filepath)
        assert self._file.is_file()

        self._datetime_format = None
        self.messages = None
        self.df = None

        self._logger = logging.getLogger(__name__).\
            getChild(self.__class__.__name__).getChild(str(id(self)))

    def write_df_to_csv(self, filename):
        if self.df is not None:
            self.df.to_csv(filename, index=False)
        else:
            self._logger.error("Failed writing to csv. Parse file first.")

    def _add_metadata(self):
        self.df['weekday'] = self.df['datetime'].dt.day_name()
        self.df["hour"] = self.df["datetime"].dt.hour
        self.df['words'] = \
            self.df['message'].apply(lambda s: len(s.split(' ')))
        self.df['letters'] = self.df['message'].apply(lambda s: len(s))

    @abstractmethod
    def parse_file_into_df():
        pass


class SignalParser(Parser):
    def __init__(self, filepath):
        super().__init__(filepath)
        self.DATEREG = r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]'

    def parse_file_into_df(self):
        self._read_file_into_list()
        parsed_messages = []
        for msg in self.messages:
            parsed_msg = self._parse_message(msg)
            if parsed_msg:
                parsed_messages.append(parsed_msg)
        self.df = pd.DataFrame(parsed_messages)
        self._logger.info("Finished parsing chatlog into dataframe.")
        self._add_metadata()
        self._logger.info("Finished adding metadata to dataframe.")

    def _read_file_into_list(self):
        self.messages = []
        with self._file.open(encoding="utf-8") as f:
            messages_raw = reversed(list(f))
        buffer = []
        for line in messages_raw:
            line = line.strip()
            if not line:
                continue
            if re.match(self.DATEREG, line):
                if buffer:
                    buffer.append(line)
                    buffer.reverse()
                    self.messages.append(' '.join(buffer))
                    buffer.clear()
                else:
                    self.messages.append(line)
            else:
                buffer.append(line)
        self._logger.info(f"Finished reading {len(self.messages)} messages.")

    def _parse_message(self, msg):
        datetime_raw, msg = msg.split(']', 1)
        datetime = datetimeparser.parse(datetime_raw[1:])
        author, msg = msg.split(':', 1)
        author = author.strip()
        msg = msg.strip()
        parsed_message = {
            'datetime': datetime,
            'author': author,
            'message': msg
        }
        return parsed_message


class WhatsAppParser(Parser):
    def __init__(self, filepath):
        super().__init__(filepath)
        self.DATEREG = r'^((\d{1})|(\d{2}))((\.)|(\/))((\d{1})|(\d{2}))((\.)|(\/))((\d{2}))'

    def parse_file_into_df(self):
        self._read_file_into_list()
        self._infer_datatime_format()

        parsed_messages = []
        for mess in self.messages:
            parsed_mess = self._parse_message(mess)
            if parsed_mess:
                parsed_messages.append(parsed_mess)

        self.df = pd.DataFrame(parsed_messages)
        self._logger.info("Finished parsing chatlog into dataframe.")
        self._add_metadata()
        self._logger.info("Finished adding metadata to dataframe.")

    def _read_file_into_list(self):
        self.messages = []
        buffer = []

        with self._file.open(encoding="utf-8") as f:
            messages_raw = reversed(list(f))

        for line in messages_raw:
            line = line.strip()

            if not line:
                continue

            if re.match(self.DATEREG, line):
                if buffer:
                    buffer.append(line)
                    buffer.reverse()
                    self.messages.append(' '.join(buffer))
                    buffer.clear()
                else:
                    self.messages.append(line)
            else:
                buffer.append(line)

        self._logger.info(f"Finished reading {len(self.messages)} messages.")

    def _infer_datatime_format(self):
        max_first = 0
        max_second = 0
        for line in self.messages:
            line = line.replace(r'/', '.', 2)
            day_and_month = [int(num) for num in line.split('.')[:2]]
            max_first = max(max_first, day_and_month[0])
            max_second = max(max_second, day_and_month[1])
            if (max_first > 12) and (max_second > 12):
                raise ValueError(f"Invalid date format: {line}")

        if (max_first > 12 and max_second <= 12):
            self._logger.info("Inferred day first format.")
            self._datetime_format = StartOfDateType.DAY
        elif (max_first <= 12 and max_second > 12):
            self._logger.info("Inferred month first format.")
            self._datetime_format = StartOfDateType.MONTH
        else:
            self._logger.warning("Can't infer dateformat. \
                No message with day > 12. Assuming day first.")
            self._datetime_format = StartOfDateType.AMBIGUOUS

    def _parse_message(self, mess):
        if self._datetime_format in (StartOfDateType.DAY,
                                     StartOfDateType.AMBIGUOUS):
            datetime = datetimeparser.parse(mess.split('-', 1)[0],
                                            dayfirst=True, fuzzy=True)
        else:
            datetime = datetimeparser.parse(mess.split('-', 1)[0],
                                            dayfirst=False, fuzzy=True)

        author = self._get_message_author(mess)
        if author != 'System':
            body = mess.split('-', 1)[1].split(':', 1)[1].strip()
        else:
            if len(mess.split('-', 1)) == 1:
                self._logger.warning(f"Failed to parse message: {mess}.")
                self._logger.warning("Please report message format in GitHub.")
                return None
            body = mess.split('-', 1)[1]

        parsed_message = {
            'datetime': datetime,
            'author': author,
            'message': body
        }
        return parsed_message

    def _get_message_author(self, message):
        patterns = [
            r'- ([+])([0-9 ]+)(:)',
            r'- ([\w]+):',
            r'- ([\w]+[\s]+[\w]+):',
            r'- ([\w]+[\s]+[\w]+[\s]+[\w]+):',
        ]
        pattern = '|'.join(patterns)
        res = re.search(pattern, message)
        return re.sub(r'|\-|\:', '', res.group(0)).strip() if res else 'System'


class StartOfDateType(Enum):
    DAY = 1
    MONTH = 2
    AMBIGUOUS = 3
