import json
import mimetypes
import os

import httpx
from nonebot import logger

from .dify_session import DifySession, DifySessionManager
from .config import config
from .dify_client import DifyClient, ChatClient
from .common.utils import parse_markdown_text
from .common.reply_type import ReplyType
from .common import memory


class DifyBot():
    def __init__(self):
        super().__init__()
        self.sessions = DifySessionManager(DifySession)

    async def reply(self, query, user_id, session_id):
        # acquire reply content
        logger.info("[DIFY] query={}".format(query))
        logger.debug(f"[DIFY] dify_user={user_id}")
        session = self.sessions.get_session(session_id, user_id)
        logger.debug(f"[DIFY] session_id={session_id} query={query}")

        _reply_type_list, _reply_content_list = await self._reply(query, session)
        if _reply_type_list == []:
            logger.error(f"无法处理回复: {_reply_content_list}")
        return _reply_type_list, _reply_content_list

    def _get_api_base_url(self) -> str:
        return config.dify_api_base

    def _get_headers(self):
        return {
            'Authorization': f"Bearer {config.dify_api_key}"
        }

    def _get_payload(self, query, session: DifySession, response_mode):
        return {
            'inputs': {},
            "query": query,
            "response_mode": response_mode,
            "conversation_id": session.get_conversation_id(),
            "user": session.get_user()
        }

    async def _reply(self, query: str, session: DifySession):
        try:
            session.count_user_message() # 限制一个conversation中消息数，防止conversation过长
            dify_app_type = config.dify_app_type
            if dify_app_type == 'chatbot':
                _result_type_list, _result_content_list = await self._handle_chatbot(query, session)
                return _result_type_list, _result_content_list
            elif dify_app_type == 'agent':
                _result_type_list, _result_content_list = await self._handle_agent(query, session)
                return _result_type_list, _result_content_list
            elif dify_app_type == 'workflow':
                _result_type_list, _result_content_list = await self._handle_workflow(query, session)
                return _result_type_list, _result_content_list
            else:
                return [ReplyType.TEXT], ["dify_app_type must be agent, chatbot or workflow"]

        except Exception as e:
            error_info = f"[DIFY] Exception: {e}"
            logger.exception(error_info)
            return [ReplyType.TEXT], [error_info]

    async def _handle_chatbot(self, query: str, session: DifySession):
        # # TODO: 获取response部分抽取为公共函数
        # base_url = self._get_api_base_url()
        # chat_url = f'{base_url}/chat-messages'
        # headers = self._get_headers()
        api_key = config.dify_api_key
        api_base = config.dify_api_base
        chat_client = ChatClient(api_key, api_base)
        response_mode = 'blocking'
        payload = self._get_payload(query, session, response_mode)
        files = await self._get_upload_files(session)
        # # response = requests.post(chat_url, headers=headers, json=payload)
        # async with httpx.AsyncClient() as client:
        #     logger.debug(f"Ready to connect {chat_url} with {payload}")
        #     response = await client.post(chat_url, headers=headers, json=payload, timeout=60)
        response = await chat_client.create_chat_message(
            inputs=payload['inputs'],
            query=payload['query'],
            user=payload['user'],
            response_mode=payload['response_mode'],
            conversation_id=payload['conversation_id'],
            files=files
        )
        if response.status_code != 200:
            error_info = f"[DIFY] response text={response.text} status_code={response.status_code}"
            logger.warning(error_info)
            return [""], [error_info]

        rsp_data = response.json()
        logger.debug("[DIFY] usage {}".format(rsp_data.get('metadata', {}).get('usage', 0)))

        answer = rsp_data['answer']
        logger.debug(f"response data: {rsp_data}")
        parsed_content = parse_markdown_text(answer)

        replies_type = []
        replies_context = []

        for item in parsed_content:
            if item['type'] == 'image':
                image_url = self._fill_file_base_url(item['content'])
                # image = self._download_image(image_url)
                replies_type.append(ReplyType.IMAGE_URL)
                replies_context.append(image_url)
            elif item['type'] == 'file':
                file_url = self._fill_file_base_url(item['content'])
                # file_path = self._download_file(file_url)
                replies_type.append(ReplyType.FILE)
                replies_context.append(file_url)
            elif item['type'] == 'text':
                content = item['content']
                replies_type.append(ReplyType.TEXT)
                replies_context.append(content)
            else:
                logger.warning(f"[DIFY] Unknown type: {item['type']}, content: {item['content']}")
                content = item['content']
                replies_type.append(ReplyType.TEXT)
                replies_context.append(content)
            logger.debug(f"[DIFY] reply_item={replies_type[-1]}, {replies_context[-1]}")

        # 设置dify conversation_id, 依靠dify管理上下文
        if session.get_conversation_id() == '':
            session.set_conversation_id(rsp_data['conversation_id'])

        return replies_type, replies_context

    async def _handle_agent(self, query: str, session: DifySession):
        # TODO: 获取response抽取为公共函数
        base_url = self._get_api_base_url()
        chat_url = f'{base_url}/chat-messages'
        headers = self._get_headers()
        response_mode = 'streaming'
        payload = self._get_payload(query, session, response_mode)
        # response = requests.post(chat_url, headers=headers, json=payload)
        async with httpx.AsyncClient() as client:
            response = await client.post(chat_url, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            error_info = f"[DIFY] response text={response.text} status_code={response.status_code}"
            logger.warning(error_info)
            return [""], [error_info]
        msgs, conversation_id = self._handle_sse_response(response)
        
        replies_type = []
        replies_context = []
        for msg in msgs:
            if msg['type'] == 'agent_message':
                content = msg['content']
                replies_type.append(ReplyType.TEXT)
                replies_context.append(content)
            elif msg['type'] == 'message_file':
                content = msg['content']['url']
                replies_type.append(ReplyType.IMAGE_URL)
                replies_context.append(content)
            else:
                logger.warning(f"[DIFY] Unknown type: {msg['type']}, content: {msg['content']}")
                content = msg['content']
                replies_type.append(ReplyType.IMAGE_URL)
                replies_context.append(content)
            logger.debug(f"[DIFY] reply_item={replies_type[-1]}, {replies_context[-1]}")

        if session.get_conversation_id() == '':
            session.set_conversation_id(conversation_id)
        return replies_type, replies_context

    async def _handle_workflow(self, query: str, session: DifySession):
        base_url = self._get_api_base_url()
        workflow_url = f'{base_url}/workflows/run'
        headers = self._get_headers()
        payload = self._get_workflow_payload(query, session)
        # response = requests.post(workflow_url, headers=headers, json=payload)
        async with httpx.AsyncClient() as client:
            response = await client.post(workflow_url, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            error_info = f"[DIFY] response text={response.text} status_code={response.status_code}"
            logger.warning(error_info)
            return [""], [error_info]

        rsp_data = response.json()
        reply_type = ReplyType.TEXT
        reply_content = rsp_data['data']['outputs']['text']
        return [reply_type], [reply_content]

    async def _get_upload_files(self, session: DifySession):
        session_id = session.get_session_id()
        # logger.debug(f"Image cache: {memory.USER_IMAGE_CACHE}")
        img_cache = memory.USER_IMAGE_CACHE.get(session_id)
        if not img_cache or not config.dify_image_upload_enable:
            return None
        api_key = config.dify_api_key
        api_base = config.dify_api_base
        dify_client = DifyClient(api_key, api_base)
        path = img_cache.get("path")
        with open(path, 'rb') as file:
            logger.debug(f"Uploading file {path} to Dify.")
            file_name = os.path.basename(path)
            file_type, _ = mimetypes.guess_type(file_name)
            files = {
                'file': (file_name, file, file_type)
            }
            response = await dify_client.file_upload(user=session.get_user(), files=files)
            response.raise_for_status()

        if response.status_code != 200 and response.status_code != 201:
            # 清理图片缓存
            memory.USER_IMAGE_CACHE[session_id] = None
            # 清除图片
            os.remove(path)
            error_info = f"[DIFY] response text={response.text} status_code={response.status_code} when upload file"
            logger.warning(error_info)
            return [""], [error_info]
        
        # 清理图片缓存
        memory.USER_IMAGE_CACHE[session_id] = None
        # 清除图片
        os.remove(path)

        file_upload_data = response.json()
        logger.debug("[DIFY] upload file {}".format(file_upload_data))
        return [
            {
                "type": "image",
                "transfer_method": "local_file",
                "upload_file_id": file_upload_data['id']
            }
        ]
    
    def _fill_file_base_url(self, url: str):
        if url.startswith("https://") or url.startswith("http://"):
            return url
        # 补全文件base url, 默认使用去掉"/v1"的dify api base url
        return self._get_file_base_url() + url

    def _get_file_base_url(self) -> str:
        return self._get_api_base_url().replace("/v1", "")

    def _get_workflow_payload(self, query, session: DifySession):
        return {
            'inputs': {
                "query": query
            },
            "response_mode": "blocking",
            "user": session.get_user()
        }

    def _parse_sse_event(self, event_str):
        """
        Parses a single SSE event string and returns a dictionary of its data.
        """
        event_prefix = "data: "
        if not event_str.startswith(event_prefix):
            return None
        trimmed_event_str = event_str[len(event_prefix):]

        # Check if trimmed_event_str is not empty and is a valid JSON string
        if trimmed_event_str:
            try:
                event = json.loads(trimmed_event_str)
                return event
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from SSE event: {trimmed_event_str}")
                return None
        else:
            logger.warning("Received an empty SSE event.")
            return None

    # TODO: 异步返回events
    def _handle_sse_response(self, response: httpx.Response):
        events = []
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                event = self._parse_sse_event(decoded_line)
                if event:
                    events.append(event)

        merged_message = []
        accumulated_agent_message = ''
        conversation_id = None
        for event in events:
            event_name = event['event']
            if event_name == 'agent_message' or event_name == 'message':
                accumulated_agent_message += event['answer']
                logger.debug("[DIFY] accumulated_agent_message: {}".format(accumulated_agent_message))
                # 保存conversation_id
                if not conversation_id:
                    conversation_id = event['conversation_id']
            elif event_name == 'agent_thought':
                self._append_agent_message(accumulated_agent_message, merged_message)
                accumulated_agent_message = ''
                logger.debug("[DIFY] agent_thought: {}".format(event))
            elif event_name == 'message_file':
                self._append_agent_message(accumulated_agent_message, merged_message)
                accumulated_agent_message = ''
                self._append_message_file(event, merged_message)
            elif event_name == 'message_replace':
                # TODO: handle message_replace
                pass
            elif event_name == 'error':
                logger.error("[DIFY] error: {}".format(event))
                raise Exception(event)
            elif event_name == 'message_end':
                self._append_agent_message(accumulated_agent_message, merged_message)
                logger.debug("[DIFY] message_end usage: {}".format(event['metadata']['usage']))
                break
            else:
                logger.warning("[DIFY] unknown event: {}".format(event))
        
        if not conversation_id:
            raise Exception("conversation_id not found")
        
        return merged_message, conversation_id

    def _append_agent_message(self, accumulated_agent_message,  merged_message):
        if accumulated_agent_message:
            merged_message.append({
                'type': 'agent_message',
                'content': accumulated_agent_message,
            })

    def _append_message_file(self, event: dict, merged_message: list):
        if event.get('type') != 'image':
            logger.warning("[DIFY] unsupported message file type: {}".format(event))
        merged_message.append({
            'type': 'message_file',
            'content': event,
        })