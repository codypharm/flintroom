require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json'))) rescue {}

Pod::Spec.new do |s|
  s.name           = 'RoomAudio'
  s.version        = '0.1.0'
  s.summary        = "Flintroom's owned audio layer: the voice-processed capture/playback pair"
  s.description    = 'The 16 kHz mono capture and playback pair the live room runs on, with Apple voice processing engaged.'
  s.author         = 'Flintroom'
  s.homepage       = 'https://www.flintroom.app'
  s.platforms      = { :ios => '15.1' }
  s.source         = { git: '' }
  s.license        = { :type => 'UNLICENSED' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.source_files = '*.swift'
end
