import aioesphomeapi
import asyncio
import os

async def main():

	print("connect to api server")
	# Values live in sites/local/secrets.yaml; export them before running:
	#   ESPHOME_HOST, ESPHOME_NOISE_PSK
	host = os.environ["ESPHOME_HOST"]
	password = os.environ["ESPHOME_NOISE_PSK"]
	print(host)
	api = aioesphomeapi.APIClient(host, 6053, password=None, noise_psk=password)
	await api.connect(login=True)
	# await api.connect()

	print(api.api_version)

	device_info = await api.device_info()
	print(device_info)

	

	def cb(state):
		if type(state) == aioesphomeapi.CameraState:
			try:
				with open('out/x.jpg','wb') as out:
					out.write(state.image)
				print('image written')
			except Exception as e:
				print(e)
		else:
			print(state)

	api.subscribe_states(cb)

	entities = await api.list_entities_services()
	print(entities)

loop = asyncio.get_event_loop()
loop.run_until_complete(main())