package sfu

import (
	"encoding/json"
	"log"
	"sync"

	"ai-call-pion/audio"
	"github.com/pion/webrtc/v3"
)

type Session struct {
	ID             string
	peerConnection *webrtc.PeerConnection
	audioTrack     *webrtc.TrackLocalStaticSample
	pcmInChan      chan []byte
	pcmOutChan     chan []byte
	mu             sync.Mutex
}

func NewSession(id string) *Session {
	return &Session{
		ID:         id,
		pcmInChan:  make(chan []byte, 100),
		pcmOutChan: make(chan []byte, 100),
	}
}

func (s *Session) ProcessOffer(sdp string) (string, error) {
	pc, err := s.NewPeerConnection()
	if err != nil {
		return "", err
	}
	s.peerConnection = pc

	// Create a track for AI audio output (to browser)
	audioTrack, err := webrtc.NewTrackLocalStaticSample(webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeOpus}, "audio", "pion")
	if err != nil {
		return "", err
	}
	s.audioTrack = audioTrack

	_, err = pc.AddTrack(audioTrack)
	if err != nil {
		return "", err
	}

	err = pc.SetRemoteDescription(webrtc.SessionDescription{Type: webrtc.SDPTypeOffer, SDP: sdp})
	if err != nil {
		return "", err
	}

	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		return "", err
	}

	err = pc.SetLocalDescription(answer)
	if err != nil {
		return "", err
	}

	return answer.SDP, nil
}

func (s *Session) AddIceCandidate(candidateJSON string) {
	var candidate webrtc.ICECandidateInit
	if err := json.Unmarshal([]byte(candidateJSON), &candidate); err != nil {
		log.Printf("Failed to unmarshal ICE candidate: %v", err)
		return
	}
	if err := s.peerConnection.AddICECandidate(candidate); err != nil {
		log.Printf("Failed to add ICE candidate: %v", err)
	}
}

func (s *Session) PlayAudio(pcmData []byte) {
	codec := audio.NewRTPCodec()
	resampler, _ := audio.NewResampler(24000, 48000)
	
	pcm48, _ := resampler.ResampleReal(pcmData)
	opus, err := codec.Encode(pcm48)
	if err != nil {
		return
	}

	s.audioTrack.WriteSample(webrtc.Sample{
		Data:     opus,
		Duration: audio.OpusFrameDuration,
	})
}

func (s *Session) GetAudioStream() chan []byte {
	return s.pcmInChan
}

func (s *Session) Close() {
	if s.peerConnection != nil {
		s.peerConnection.Close()
	}
	close(s.pcmInChan)
	close(s.pcmOutChan)
}
